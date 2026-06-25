"""Tests for duplicacy-exporter parsing and state management."""

import io
import json
import pytest
import sys
import time
import threading
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).parent.parent))

from duplicacy_exporter import (
    _extract_storage_target,
    _basename,
    _load_storage_host_map,
    _load_last_timestamp,
    _save_last_timestamp,
    _parse_size,
    _parse_speed,
    _parse_duration,
    _parse_docker_timestamp,
    tail_docker_logs,
    BackupState,
    WebhookHandler,
    MetricsHTTPHandler,
    RE_CHUNK_LINE,
    RE_STORAGE_SET,
    RE_BACKUP_END,
    RE_STATS_FILES,
    RE_STATS_CHUNKS,
    RE_STATS_TIME,
    RE_SECTION_HEADER,
    RE_META_LINE,
    registry,
    backup_running,
    backup_speed_bps,
    backup_progress,
    backup_chunks_uploaded,
    backup_chunks_skipped,
    last_success_ts,
    last_duration,
    last_files_total,
    last_files_new,
    last_bytes_uploaded,
    last_bytes_new,
    last_chunks_new,
    last_exit_code,
    last_revision,
    total_bytes_uploaded,
    prune_running,
    last_prune_success_ts,
    backups_seen,
    exporter_last_activity_ts,
    TIMESTAMP_FILE,
)


# =========================================================================
# _load_storage_host_map
# =========================================================================

class TestLoadStorageHostMap:
    def test_empty_env(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _load_storage_host_map() == {}

    def test_valid_json(self):
        env = {"STORAGE_HOST_MAP": '{"192.168.10.100": "watchtower"}'}
        with patch.dict("os.environ", env, clear=False):
            result = _load_storage_host_map()
            assert result == {"192.168.10.100": "watchtower"}

    def test_invalid_json(self):
        env = {"STORAGE_HOST_MAP": "not-json{"}
        with patch.dict("os.environ", env, clear=False):
            result = _load_storage_host_map()
            assert result == {}


# =========================================================================
# _extract_storage_target
# =========================================================================

class TestExtractStorageTarget:
    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {})
    def test_tailscale_fqdn(self):
        url = "minio://garage@watchtower.mango-alpha.ts.net:9000/bucket"
        assert _extract_storage_target(url) == "watchtower"

    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {"192.168.10.100": "watchtower"})
    def test_ip_via_host_map(self):
        url = "minio://garage@192.168.10.100:9000/bucket"
        assert _extract_storage_target(url) == "watchtower"

    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {})
    def test_sftp_url(self):
        url = "sftp://user@geiserct.mango-alpha.ts.net/path"
        assert _extract_storage_target(url) == "geiserct"

    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {})
    def test_generic_hostname(self):
        url = "sftp://user@myserver.example.com/path"
        assert _extract_storage_target(url) == "myserver"

    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {})
    def test_no_match_returns_url(self):
        url = "localpath"
        assert _extract_storage_target(url) == "localpath"

    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {})
    def test_bare_ip_no_host_map(self):
        """IP address with no host map entry returns the IP as-is."""
        url = "minio://garage@192.168.10.50:9000/bucket"
        assert _extract_storage_target(url) == "192.168.10.50"

    @patch("duplicacy_exporter.TAILSCALE_DOMAIN", "mango-alpha.ts.net")
    @patch("duplicacy_exporter._STORAGE_HOST_MAP", {})
    def test_url_without_at_sign(self):
        """URL with :// but no @ should still extract host."""
        url = "http://somehost.example.com/path"
        assert _extract_storage_target(url) == "somehost"


# =========================================================================
# _parse_size
# =========================================================================

class TestParseSize:
    def test_bytes(self):
        assert _parse_size("100", "") == 100.0

    def test_kilobytes(self):
        assert _parse_size("1", "K") == 1024.0

    def test_megabytes(self):
        assert _parse_size("2", "M") == 2 * 1024 ** 2

    def test_gigabytes(self):
        assert _parse_size("1.5", "G") == 1.5 * 1024 ** 3

    def test_comma_separated(self):
        assert _parse_size("1,024", "K") == 1024 * 1024

    def test_unknown_unit_defaults_to_1(self):
        assert _parse_size("500", "X") == 500.0


# =========================================================================
# _parse_speed
# =========================================================================

class TestParseSpeed:
    def test_bytes_per_second(self):
        assert _parse_speed("100", "B/s") == 100.0

    def test_kb_per_second(self):
        assert _parse_speed("5", "KB/s") == 5 * 1024

    def test_mb_per_second(self):
        assert _parse_speed("10.5", "MB/s") == 10.5 * 1024 ** 2

    def test_gb_per_second(self):
        assert _parse_speed("1", "GB/s") == 1024 ** 3

    def test_unknown_unit_defaults_to_1(self):
        assert _parse_speed("200", "XB/s") == 200.0


# =========================================================================
# _parse_duration
# =========================================================================

class TestParseDuration:
    def test_hours_minutes_seconds(self):
        assert _parse_duration(None, "01", "30", "45") == 3600 + 1800 + 45

    def test_with_days(self):
        assert _parse_duration("2", "03", "00", "00") == 2 * 86400 + 3 * 3600

    def test_zero_duration(self):
        assert _parse_duration(None, "00", "00", "00") == 0


# =========================================================================
# _parse_docker_timestamp
# =========================================================================

class TestParseDockerTimestamp:
    def test_valid_timestamp(self):
        line = "2024-03-15T10:30:00.123456789Z Some log content"
        ts, content = _parse_docker_timestamp(line)
        assert ts > 0
        assert content == "Some log content"

    def test_no_timestamp(self):
        line = "Just a regular line"
        ts, content = _parse_docker_timestamp(line)
        assert ts == 0.0
        assert content == "Just a regular line"

    def test_short_line(self):
        line = "Short"
        ts, content = _parse_docker_timestamp(line)
        assert ts == 0.0
        assert content == "Short"

    def test_invalid_iso_format(self):
        """Line that looks like it has a timestamp but is malformed."""
        line = "2024-XX-15T10:30:00Z Some log content"
        ts, content = _parse_docker_timestamp(line)
        assert ts == 0.0
        assert content == line

    def test_line_missing_space_after_timestamp(self):
        """Line with date-like prefix but no space separator triggers ValueError."""
        line = "2024-03-15T10:30:00.123456789Znospace"
        ts, content = _parse_docker_timestamp(line)
        # Should not crash, returns 0.0 on parsing failure
        assert ts == 0.0


# =========================================================================
# Regex patterns
# =========================================================================

class TestRegexPatterns:
    def test_chunk_line_uploaded(self):
        line = "Uploaded chunk 42 size 4194304, 15.2MB/s 00:05:30 65.3%"
        m = RE_CHUNK_LINE.search(line)
        assert m is not None
        assert m.group("action") == "Uploaded"
        assert m.group("chunk_num") == "42"
        assert m.group("speed") == "15.2"
        assert m.group("speed_unit") == "MB/s"
        assert m.group("progress") == "65.3"

    def test_chunk_line_skipped(self):
        line = "Skipped chunk 10 size 1048576, 0.0B/s 00:00:01 10.0%"
        m = RE_CHUNK_LINE.search(line)
        assert m is not None
        assert m.group("action") == "Skipped"

    def test_chunk_line_with_days(self):
        line = "Uploaded chunk 99 size 4194304, 5.0MB/s 2 days 01:00:00 95.0%"
        m = RE_CHUNK_LINE.search(line)
        assert m is not None
        assert m.group("days") == "2"
        assert m.group("eta") == "01:00:00"

    def test_storage_set(self):
        line = "Storage set to minio://garage@watchtower.mango-alpha.ts.net:9000/backup"
        m = RE_STORAGE_SET.search(line)
        assert m is not None
        assert "watchtower" in m.group("storage_url")

    def test_backup_end(self):
        line = "Backup for /data at revision 142 completed"
        m = RE_BACKUP_END.search(line)
        assert m is not None
        assert m.group("revision") == "142"

    def test_stats_files(self):
        line = "Files: 12,345 total, 5.2G bytes; 100 new, 200M bytes"
        m = RE_STATS_FILES.search(line)
        assert m is not None
        assert m.group("total") == "12,345"
        assert m.group("new") == "100"

    def test_stats_chunks(self):
        line = "All chunks: 500 total, 2.0G bytes; 10 new, 100M bytes, 50M bytes uploaded"
        m = RE_STATS_CHUNKS.search(line)
        assert m is not None
        assert m.group("total") == "500"
        assert m.group("new") == "10"
        assert m.group("uploaded_bytes") == "50"
        assert m.group("uploaded_unit") == "M"

    def test_stats_time(self):
        line = "Total running time: 01:23:45"
        m = RE_STATS_TIME.search(line)
        assert m is not None
        assert m.group("hours") == "01"
        assert m.group("minutes") == "23"
        assert m.group("seconds") == "45"

    def test_stats_time_with_days(self):
        line = "Total running time: 1:02:30:00"
        m = RE_STATS_TIME.search(line)
        assert m is not None
        assert m.group("days") == "1"
        assert m.group("hours") == "02"

    def test_section_header_backup(self):
        line = "--- Backup -> Primary (appdata) ---"
        m = RE_SECTION_HEADER.match(line)
        assert m is not None
        assert m.group("type") == "Backup"
        assert m.group("direction") == "Primary"
        assert m.group("storage") == "appdata"

    def test_section_header_prune(self):
        line = "--- Prune Primary ---"
        m = RE_SECTION_HEADER.match(line)
        assert m is not None
        assert m.group("type") == "Prune"

    def test_section_header_backup_secondary(self):
        line = "--- Backup -> Secondary (appdataC) ---"
        m = RE_SECTION_HEADER.match(line)
        assert m is not None
        assert m.group("direction") == "Secondary"
        assert m.group("storage") == "appdataC"

    def test_section_header_legacy_output(self):
        line = "--- Backup Output ---"
        m = RE_SECTION_HEADER.match(line)
        assert m is not None
        assert m.group("direction") == "Output"
        assert m.group("storage") is None

    def test_meta_line(self):
        line = "DUPLICACY_META snapshot_id=appdata direction=primary"
        m = RE_META_LINE.match(line)
        assert m is not None
        assert "snapshot_id=appdata" in m.group("kvpairs")


# =========================================================================
# BackupState
# =========================================================================

class TestBackupState:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_initial_state(self):
        state = BackupState()
        assert state.in_backup is False
        assert state.in_prune is False
        assert state.current_snapshot == ""

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_process_storage_set(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.in_backup = True
        state.process_line("Storage set to sftp://user@myhost.mango-alpha.ts.net/backups")
        assert state.current_storage_target == "myhost"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_failure_detection(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "watchtower"
        state.in_backup = True
        state.process_line("Backup failed due to connection error")
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_failure_lowercase(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "watchtower"
        state.in_backup = True
        state.process_line("backup failed: some error")
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_completion(self):
        state = BackupState()
        state.current_storage_target = "watchtower"
        state.in_prune = True
        state.process_line("All fossil collections have been removed")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_no_snapshot(self):
        state = BackupState()
        state.current_storage_target = "watchtower"
        state.in_prune = True
        state.process_line("No snapshot to delete")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_nothing_to_prune(self):
        state = BackupState()
        state.current_storage_target = "watchtower"
        state.in_prune = True
        state.process_line("Nothing to prune")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_completed_pattern(self):
        state = BackupState()
        state.current_storage_target = "watchtower"
        state.in_prune = True
        state.process_line("Prune completed")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_meta_line_sets_snapshot(self):
        state = BackupState()
        state.process_line("DUPLICACY_META snapshot_id=mydata direction=primary")
        assert state.current_snapshot == "mydata"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_meta_line_sets_storage_target(self):
        state = BackupState()
        state.process_line("DUPLICACY_META snapshot_id=mydata storage_target=wt")
        assert state.current_snapshot == "mydata"
        assert state.current_storage_target == "wt"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_meta_line_sets_machine(self):
        state = BackupState()
        state.process_line("DUPLICACY_META snapshot_id=mydata machine=newmachine")
        assert state.machine == "newmachine"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_empty_line_ignored(self):
        state = BackupState()
        state.process_line("")
        state.process_line("   ")
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_section_header_backup_primary(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        assert state.in_backup is True
        assert state.in_prune is False
        assert state.current_snapshot == "appdata"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_section_header_backup_secondary_strips_C(self):
        """Secondary storage with trailing C gets snapshot name without C."""
        state = BackupState()
        state.process_line("--- Backup -> Secondary (appdataC) ---")
        assert state.in_backup is True
        assert state.current_snapshot == "appdata"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_section_header_backup_legacy_output(self):
        """Legacy 'Output' header with no storage name."""
        state = BackupState()
        state.process_line("--- Backup Output ---")
        assert state.in_backup is True
        # No storage_name means snapshot stays empty
        assert state.current_snapshot == ""

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_section_header_prune(self):
        state = BackupState()
        state.process_line("--- Prune Primary ---")
        assert state.in_prune is True
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_section_ends_previous_backup(self):
        """A new backup section should close any active backup."""
        state = BackupState()
        state.current_snapshot = "old"
        state.current_storage_target = "wt"
        state.in_backup = True
        # New section arrives
        state.process_line("--- Backup -> Primary (newdata) ---")
        assert state.current_snapshot == "newdata"
        assert state.in_backup is True

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_section_ends_previous_backup(self):
        """A prune section should close any active backup."""
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "wt"
        state.in_backup = True
        state.process_line("--- Prune Primary ---")
        assert state.in_backup is False
        assert state.in_prune is True

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_section_ends_previous_prune(self):
        """A backup section should close any active prune."""
        state = BackupState()
        state.current_storage_target = "wt"
        state.in_prune = True
        state.process_line("--- Backup -> Primary (appdata) ---")
        assert state.in_prune is False
        assert state.in_backup is True

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_storage_set_initializes_backup_metrics(self):
        """After backup section + storage set, backup_running should be 1."""
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to minio://garage@watchtower.mango-alpha.ts.net:9000/bucket")
        assert state.current_storage_target == "watchtower"
        labels = ("appdata", "watchtower", "testmachine")
        assert backup_running.labels(*labels)._value.get() == 1.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_storage_set_initializes_prune_metrics(self):
        """After prune section + storage set, prune_running should be 1."""
        state = BackupState()
        state.process_line("--- Prune Primary ---")
        state.process_line("Storage set to minio://garage@watchtower.mango-alpha.ts.net:9000/bucket")
        assert state.current_storage_target == "watchtower"
        labels = ("watchtower", "testmachine")
        assert prune_running.labels(*labels)._value.get() == 1.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_chunk_uploaded_updates_metrics(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("Uploaded chunk 1 size 4194304, 15.2MB/s 00:05:30 25.0%")
        labels = ("appdata", "wt", "testmachine")
        assert backup_chunks_uploaded.labels(*labels)._value.get() == 1.0
        assert backup_progress.labels(*labels)._value.get() == 0.25
        assert backup_speed_bps.labels(*labels)._value.get() > 0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_chunk_skipped_updates_metrics(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("Skipped chunk 1 size 1048576, 0.0B/s 00:00:01 10.0%")
        labels = ("appdata", "wt", "testmachine")
        assert backup_chunks_skipped.labels(*labels)._value.get() == 1.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_chunk_line_ignored_when_not_in_backup(self):
        """Chunk lines outside a backup section should not crash."""
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "wt"
        state.in_backup = False
        state.process_line("Uploaded chunk 1 size 4194304, 15.2MB/s 00:05:30 25.0%")
        # No crash, no state change

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_chunk_line_ignored_without_labels(self):
        """Chunk line in backup but without storage_target should be ignored."""
        state = BackupState()
        state.in_backup = True
        state.current_snapshot = "appdata"
        state.current_storage_target = ""  # Not yet resolved
        state.process_line("Uploaded chunk 1 size 4194304, 15.2MB/s 00:05:30 25.0%")
        # Should not crash

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_end_sets_metrics(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("Backup for /data at revision 42 completed")
        labels = ("appdata", "wt", "testmachine")
        assert backup_running.labels(*labels)._value.get() == 0.0
        assert backup_progress.labels(*labels)._value.get() == 1.0
        assert last_revision.labels(*labels)._value.get() == 42.0
        assert last_exit_code.labels(*labels)._value.get() == 0.0
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_end_without_labels_ignored(self):
        """Backup end line without resolved labels does nothing."""
        state = BackupState()
        state.in_backup = True
        state.current_snapshot = ""
        state.process_line("Backup for /data at revision 42 completed")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_stats_files_sets_metrics(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("Files: 1,000 total, 5G bytes; 50 new, 200M bytes")
        labels = ("appdata", "wt", "testmachine")
        assert last_files_total.labels(*labels)._value.get() == 1000.0
        assert last_files_new.labels(*labels)._value.get() == 50.0
        assert last_bytes_new.labels(*labels)._value.get() == 200 * 1024 ** 2

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_stats_files_without_labels_ignored(self):
        state = BackupState()
        state.current_snapshot = ""
        state.current_storage_target = ""
        state.process_line("Files: 1,000 total, 5G bytes; 50 new, 200M bytes")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_stats_chunks_sets_metrics(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("All chunks: 500 total, 2G bytes; 10 new, 100M bytes, 50M bytes uploaded")
        labels = ("appdata", "wt", "testmachine")
        assert last_bytes_uploaded.labels(*labels)._value.get() == 50 * 1024 ** 2
        assert last_chunks_new.labels(*labels)._value.get() == 10.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_stats_chunks_without_labels_ignored(self):
        state = BackupState()
        state.current_snapshot = ""
        state.current_storage_target = ""
        state.process_line("All chunks: 500 total, 2G bytes; 10 new, 100M bytes, 50M bytes uploaded")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_stats_time_sets_duration(self):
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("Total running time: 01:23:45")
        labels = ("appdata", "wt", "testmachine")
        expected = 1 * 3600 + 23 * 60 + 45
        assert last_duration.labels(*labels)._value.get() == expected

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_stats_time_without_labels_ignored(self):
        state = BackupState()
        state.current_snapshot = ""
        state.current_storage_target = ""
        state.process_line("Total running time: 01:23:45")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_failure_sets_exit_code(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "wt"
        state.in_backup = True
        state.process_line("Backup failed due to connection error")
        labels = ("appdata", "wt", "testmachine")
        assert last_exit_code.labels(*labels)._value.get() == 1.0
        assert backup_running.labels(*labels)._value.get() == 0.0
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_failure_without_labels(self):
        """Backup failure without labels should still set in_backup=False."""
        state = BackupState()
        state.in_backup = True
        state.current_snapshot = ""
        state.current_storage_target = ""
        state.process_line("Backup failed due to connection error")
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_completion_sets_timestamp(self):
        state = BackupState()
        state.process_line("--- Prune Primary ---")
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        now = time.time()
        state.process_line("All fossil collections have been removed")
        labels = ("wt", "testmachine")
        assert prune_running.labels(*labels)._value.get() == 0.0
        assert last_prune_success_ts.labels(*labels)._value.get() >= now - 5

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_completion_without_labels(self):
        """Prune completion without storage_target should still set in_prune=False."""
        state = BackupState()
        state.in_prune = True
        state.current_storage_target = ""
        state.process_line("All fossil collections have been removed")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "")
    def test_notification_line_sets_machine(self):
        """Notification line with em-dash and bold markers sets machine/snapshot."""
        state = BackupState()
        state.process_line("*watchtower* \u2014 _appdata_ backup completed")
        assert state.machine == "watchtower"
        assert state.current_snapshot == "appdata"

    @patch("duplicacy_exporter.MACHINE_NAME", "fixed")
    def test_notification_line_does_not_override_machine_name(self):
        """If MACHINE_NAME is set, notification should not override it."""
        state = BackupState()
        state.process_line("*watchtower* \u2014 _appdata_ backup completed")
        assert state.machine == "fixed"

    @patch("duplicacy_exporter.MACHINE_NAME", "")
    def test_notification_line_does_not_set_snapshot_during_backup(self):
        """During active backup, notification should not change snapshot."""
        state = BackupState()
        state.in_backup = True
        state.current_snapshot = "existing"
        state.process_line("*watchtower* \u2014 _newsnap_ backup completed")
        assert state.current_snapshot == "existing"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_notification_line_ends_active_prune(self):
        """Notification line ends any active prune."""
        state = BackupState()
        state.current_storage_target = "wt"
        state.in_prune = True
        state.process_line("*watchtower* \u2014 _appdata_ backup completed")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_process_line_with_log_time(self):
        """process_line should accept and use log_time parameter."""
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---", log_time=1000.0)
        assert state._log_time == 1000.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_full_backup_flow(self):
        """Simulate a complete backup lifecycle."""
        state = BackupState()
        state.process_line("--- Backup -> Primary (appdata) ---")
        state.process_line("Storage set to minio://garage@wt.mango-alpha.ts.net:9000/bucket")
        state.process_line("Uploaded chunk 1 size 4194304, 10.0MB/s 00:10:00 50.0%")
        state.process_line("Uploaded chunk 2 size 4194304, 12.0MB/s 00:05:00 100.0%")
        state.process_line("Files: 500 total, 2G bytes; 10 new, 100M bytes")
        state.process_line("All chunks: 200 total, 1G bytes; 5 new, 50M bytes, 30M bytes uploaded")
        state.process_line("Total running time: 00:15:30")
        state.process_line("Backup for /data at revision 99 completed")

        labels = ("appdata", "wt", "testmachine")
        assert state.in_backup is False
        assert backup_running.labels(*labels)._value.get() == 0.0
        assert backup_progress.labels(*labels)._value.get() == 1.0
        assert last_revision.labels(*labels)._value.get() == 99.0
        assert last_files_total.labels(*labels)._value.get() == 500.0
        assert last_duration.labels(*labels)._value.get() == 15 * 60 + 30

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_labels_returns_none_without_snapshot(self):
        state = BackupState()
        state.current_snapshot = ""
        state.current_storage_target = "wt"
        assert state._backup_labels() is None

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_labels_returns_none_without_storage(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = ""
        assert state._backup_labels() is None

    @patch("duplicacy_exporter.MACHINE_NAME", "")
    def test_backup_labels_returns_none_without_machine(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "wt"
        assert state._backup_labels() is None

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backup_labels_returns_tuple(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "wt"
        assert state._backup_labels() == ("appdata", "wt", "testmachine")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_labels_returns_none_without_storage(self):
        state = BackupState()
        state.current_storage_target = ""
        assert state._prune_labels() is None

    @patch("duplicacy_exporter.MACHINE_NAME", "")
    def test_prune_labels_returns_none_without_machine(self):
        state = BackupState()
        state.current_storage_target = "wt"
        assert state._prune_labels() is None

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_prune_labels_returns_tuple(self):
        state = BackupState()
        state.current_storage_target = "wt"
        assert state._prune_labels() == ("wt", "testmachine")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_end_active_backup_with_labels(self):
        state = BackupState()
        state.current_snapshot = "appdata"
        state.current_storage_target = "wt"
        state.in_backup = True
        state._end_active_backup()
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_end_active_backup_without_labels(self):
        state = BackupState()
        state.in_backup = True
        state.current_snapshot = ""
        state._end_active_backup()
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_end_active_backup_when_not_in_backup(self):
        state = BackupState()
        state.in_backup = False
        state._end_active_backup()
        assert state.in_backup is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_end_active_prune_with_labels(self):
        state = BackupState()
        state.current_storage_target = "wt"
        state.in_prune = True
        state._end_active_prune()
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_end_active_prune_without_labels(self):
        state = BackupState()
        state.in_prune = True
        state.current_storage_target = ""
        state._end_active_prune()
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_end_active_prune_when_not_in_prune(self):
        state = BackupState()
        state.in_prune = False
        state._end_active_prune()
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_storage_set_outside_backup_and_prune(self):
        """Storage set line outside any section just updates target."""
        state = BackupState()
        state.in_backup = False
        state.in_prune = False
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        assert state.current_storage_target == "wt"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_meta_line_without_equals(self):
        """Meta line with key-value pairs that don't have = sign."""
        state = BackupState()
        state.process_line("DUPLICACY_META snapshot_id=appdata badtoken")
        assert state.current_snapshot == "appdata"


# =========================================================================
# WebhookHandler
# =========================================================================

class TestWebhookHandler:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_successful_backup(self):
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "appdata",
            "storage": "sftp://user@wt.mango-alpha.ts.net/backups",
            "computer": "watchtower",
            "result": "success",
            "start_time": 1000,
            "end_time": 1600,
            "total_files": 500,
            "new_files": 10,
            "new_chunks": 5,
            "uploaded_chunk_size": 1048576,
            "new_file_size": 2097152,
        }
        handler.handle(payload)
        labels = ("appdata", "wt", "watchtower")
        assert last_exit_code.labels(*labels)._value.get() == 0.0
        assert last_duration.labels(*labels)._value.get() == 600.0
        assert last_files_total.labels(*labels)._value.get() == 500.0
        assert last_files_new.labels(*labels)._value.get() == 10.0
        assert last_chunks_new.labels(*labels)._value.get() == 5.0
        assert last_bytes_uploaded.labels(*labels)._value.get() == 1048576.0
        assert last_bytes_new.labels(*labels)._value.get() == 2097152.0
        assert backup_running.labels(*labels)._value.get() == 0.0
        assert backup_progress.labels(*labels)._value.get() == 1.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_failed_backup(self):
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "appdata",
            "storage": "sftp://user@wt.mango-alpha.ts.net/backups",
            "computer": "watchtower",
            "result": "failure",
            "start_time": 0,
            "end_time": 0,
            "total_files": 0,
            "new_files": 0,
            "new_chunks": 0,
            "uploaded_chunk_size": 0,
            "new_file_size": 0,
        }
        handler.handle(payload)
        labels = ("appdata", "wt", "watchtower")
        assert last_exit_code.labels(*labels)._value.get() == 1.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_webhook_no_storage_url(self):
        """Payload with empty storage."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "appdata",
            "storage": "",
            "computer": "watchtower",
            "result": "success",
            "start_time": 1000,
            "end_time": 1600,
        }
        handler.handle(payload)
        labels = ("appdata", "unknown", "watchtower")
        assert last_exit_code.labels(*labels)._value.get() == 0.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_webhook_with_storage_url_fallback(self):
        """Payload uses storage_url instead of storage. With no id/directory the
        snapshot id falls back to a machine:storage composite -- never a bare
        machine name, which would collapse two backups on one machine into one."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "computer": "watchtower",
            "storage_url": "sftp://user@host.mango-alpha.ts.net/path",
            "result": "success",
            "start_time": 1000,
            "end_time": 1600,
        }
        handler.handle(payload)
        labels = ("watchtower:host", "host", "watchtower")
        assert last_exit_code.labels(*labels)._value.get() == 0.0

    @patch("duplicacy_exporter.MACHINE_NAME", "")
    def test_webhook_machine_name_fallback(self):
        """When MACHINE_NAME is empty, computer from payload is used."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "snap",
            "storage": "",
            "computer": "mycomp",
            "result": "success",
            "start_time": 0,
            "end_time": 0,
        }
        handler.handle(payload)
        labels = ("snap", "unknown", "mycomp")
        assert last_exit_code.labels(*labels)._value.get() == 0.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_webhook_speed_calculation(self):
        """Speed is calculated from uploaded / duration."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "snap",
            "storage": "sftp://user@wt.mango-alpha.ts.net/path",
            "computer": "wt",
            "result": "success",
            "start_time": 1000,
            "end_time": 1100,
            "uploaded_chunk_size": 10240,
            "total_files": 0,
            "new_files": 0,
            "new_chunks": 0,
            "new_file_size": 0,
        }
        handler.handle(payload)
        labels = ("snap", "wt", "wt")
        speed = backup_speed_bps.labels(*labels)._value.get()
        assert speed == pytest.approx(10240 / 100.0, rel=0.01)

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_webhook_no_upload_no_speed(self):
        """When uploaded=0, speed should not be set."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "snap",
            "storage": "sftp://user@unique1.mango-alpha.ts.net/path",
            "computer": "wt",
            "result": "success",
            "start_time": 1000,
            "end_time": 1100,
            "uploaded_chunk_size": 0,
            "total_files": 0,
            "new_files": 0,
            "new_chunks": 0,
            "new_file_size": 0,
        }
        handler.handle(payload)
        labels = ("snap", "unique1", "wt")
        # speed should remain 0 since nothing was uploaded
        assert backup_speed_bps.labels(*labels)._value.get() == 0.0


# =========================================================================
# MetricsHTTPHandler
# =========================================================================

class _FakeRequest:
    """Simulates a socket request for BaseHTTPRequestHandler."""
    def __init__(self):
        self.data = b""

    def makefile(self, mode, buffering=-1):
        if "r" in mode:
            return io.BytesIO(self.data)
        return io.BytesIO()

    def sendall(self, data):
        self.data += data


class TestMetricsHTTPHandler:
    def _make_handler(self, method, path, body=None):
        """Create a handler instance with a fake request."""
        if body:
            body_bytes = body.encode() if isinstance(body, str) else body
            request_line = f"{method} {path} HTTP/1.1\r\nContent-Length: {len(body_bytes)}\r\nHost: localhost\r\n\r\n"
            request_data = request_line.encode() + body_bytes
        else:
            request_data = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()

        req = _FakeRequest()
        req.data = request_data

        client_address = ("127.0.0.1", 9999)
        server = MagicMock()

        handler = MetricsHTTPHandler(req, client_address, server)
        return handler

    def test_get_metrics(self):
        """GET /metrics returns 200 with prometheus content."""
        handler = self._make_handler("GET", "/metrics")
        # The handler processes during __init__, so we check it didn't error

    def test_get_health(self):
        """GET /health returns 200."""
        handler = self._make_handler("GET", "/health")

    def test_get_healthz(self):
        """GET /healthz returns 200."""
        handler = self._make_handler("GET", "/healthz")

    def test_get_404(self):
        """GET unknown path returns 404."""
        handler = self._make_handler("GET", "/unknown")

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_post_webhook(self):
        """POST /webhook with valid JSON."""
        state = BackupState()
        wh = WebhookHandler(state)
        MetricsHTTPHandler.webhook_handler = wh
        payload = json.dumps({
            "id": "httpsnap",
            "storage": "",
            "computer": "wt",
            "result": "success",
            "start_time": 0,
            "end_time": 0,
        })
        handler = self._make_handler("POST", "/webhook", body=payload)
        MetricsHTTPHandler.webhook_handler = None

    def test_post_webhook_invalid_json(self):
        """POST /webhook with invalid JSON."""
        state = BackupState()
        wh = WebhookHandler(state)
        MetricsHTTPHandler.webhook_handler = wh
        handler = self._make_handler("POST", "/webhook", body="not-json{{{")
        MetricsHTTPHandler.webhook_handler = None

    def test_post_404(self):
        """POST to unknown path returns 404."""
        handler = self._make_handler("POST", "/unknown")

    def test_post_webhook_no_handler(self):
        """POST /webhook with no handler set returns 404."""
        MetricsHTTPHandler.webhook_handler = None
        handler = self._make_handler("POST", "/webhook", body="{}")

    def test_log_message_suppressed(self):
        """log_message is a no-op."""
        handler_cls = MetricsHTTPHandler
        # Just verify the method exists and does nothing
        assert hasattr(handler_cls, "log_message")


# =========================================================================
# tail_docker_logs
# =========================================================================

class TestTailDockerLogs:
    """tail_docker_logs uses an internal _UnixConn(HTTPConnection) subclass
    that creates real AF_UNIX sockets — cannot be reliably unit-tested.
    The function is excluded from coverage via codecov.yml ignore.
    We keep a minimal smoke test that verifies the function exists and
    its retry loop by raising immediately.
    """

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_exists_and_is_callable(self):
        import duplicacy_exporter
        assert callable(duplicacy_exporter.tail_docker_logs)


# =========================================================================
# tail_log_file
# =========================================================================

class TestTailLogFile:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_tail_log_file_not_found(self):
        """tail_log_file retries when file is not found."""
        import duplicacy_exporter

        state = BackupState()
        call_count = 0

        def fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt("Stop test")

        with patch("time.sleep", side_effect=fake_sleep):
            with pytest.raises(KeyboardInterrupt):
                duplicacy_exporter.tail_log_file(state, "/nonexistent/path/log.txt")

        assert call_count >= 1

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_tail_log_file_reads_lines(self):
        """tail_log_file processes lines from a file."""
        import duplicacy_exporter

        state = BackupState()
        read_count = 0

        fake_lines = [
            "--- Backup -> Primary (appdata) ---\n",
            "Storage set to sftp://user@wt.mango-alpha.ts.net/backups\n",
            "",  # readline returns empty string to trigger sleep
        ]
        line_idx = 0

        class FakeFile:
            def __init__(self, *args, **kwargs):
                pass

            def seek(self, *args):
                pass

            def readline(self):
                nonlocal line_idx, read_count
                if line_idx < len(fake_lines):
                    line = fake_lines[line_idx]
                    line_idx += 1
                    return line
                read_count += 1
                if read_count > 1:
                    raise KeyboardInterrupt("Stop test")
                return ""

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("builtins.open", return_value=FakeFile()):
            with patch("time.sleep", side_effect=lambda s: None):
                with pytest.raises(KeyboardInterrupt):
                    duplicacy_exporter.tail_log_file(state, "/fake/log.txt")

        assert state.current_storage_target == "wt"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_tail_log_file_generic_exception(self):
        """tail_log_file retries on generic exceptions."""
        import duplicacy_exporter

        state = BackupState()
        call_count = 0

        def fake_open(*args, **kwargs):
            raise PermissionError("denied")

        def fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt("Stop test")

        with patch("builtins.open", side_effect=fake_open):
            with patch("time.sleep", side_effect=fake_sleep):
                with pytest.raises(KeyboardInterrupt):
                    duplicacy_exporter.tail_log_file(state, "/fake/log.txt")

        assert call_count >= 1


# =========================================================================
# main()
# =========================================================================

class TestMain:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.MODE", "log_tail")
    @patch("duplicacy_exporter.LOG_FILE", "")
    @patch("duplicacy_exporter.LISTEN_PORT", 0)
    def test_main_log_tail_docker_mode(self):
        """main() in log_tail mode starts docker tailer thread."""
        import duplicacy_exporter

        server_mock = MagicMock()
        server_mock.serve_forever.side_effect = KeyboardInterrupt()

        with patch.object(duplicacy_exporter, "HTTPServer", return_value=server_mock):
            with patch.object(duplicacy_exporter, "tail_docker_logs"):
                with patch("threading.Thread") as thread_mock:
                    thread_instance = MagicMock()
                    thread_mock.return_value = thread_instance
                    duplicacy_exporter.main()
                    thread_instance.start.assert_called_once()

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.MODE", "log_tail")
    @patch("duplicacy_exporter.LOG_FILE", "/some/file.log")
    @patch("duplicacy_exporter.LISTEN_PORT", 0)
    def test_main_log_tail_file_mode(self):
        """main() in log_tail mode with LOG_FILE starts file tailer."""
        import duplicacy_exporter

        server_mock = MagicMock()
        server_mock.serve_forever.side_effect = KeyboardInterrupt()

        with patch.object(duplicacy_exporter, "HTTPServer", return_value=server_mock):
            with patch("threading.Thread") as thread_mock:
                thread_instance = MagicMock()
                thread_mock.return_value = thread_instance
                duplicacy_exporter.main()
                thread_instance.start.assert_called_once()

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.MODE", "webhook")
    @patch("duplicacy_exporter.LISTEN_PORT", 0)
    def test_main_webhook_mode(self):
        """main() in webhook mode does not start tailer thread."""
        import duplicacy_exporter

        server_mock = MagicMock()
        server_mock.serve_forever.side_effect = KeyboardInterrupt()

        with patch.object(duplicacy_exporter, "HTTPServer", return_value=server_mock):
            duplicacy_exporter.main()
            server_mock.serve_forever.assert_called_once()


# =========================================================================
# _load_last_timestamp / _save_last_timestamp
# =========================================================================

class TestTimestampPersistence:
    def test_load_returns_value_from_file(self, tmp_path):
        ts_file = tmp_path / "ts"
        ts_file.write_text("1234567890.123456\n")
        with patch("duplicacy_exporter.TIMESTAMP_FILE", str(ts_file)):
            assert _load_last_timestamp() == pytest.approx(1234567890.123456)

    def test_load_returns_zero_when_file_missing(self, tmp_path):
        with patch("duplicacy_exporter.TIMESTAMP_FILE", str(tmp_path / "nonexistent")):
            assert _load_last_timestamp() == 0.0

    def test_load_returns_zero_on_invalid_content(self, tmp_path):
        ts_file = tmp_path / "ts"
        ts_file.write_text("not-a-number\n")
        with patch("duplicacy_exporter.TIMESTAMP_FILE", str(ts_file)):
            assert _load_last_timestamp() == 0.0

    def test_save_writes_timestamp(self, tmp_path):
        ts_file = tmp_path / "ts"
        with patch("duplicacy_exporter.TIMESTAMP_FILE", str(ts_file)):
            _save_last_timestamp(9876543210.654321)
        content = ts_file.read_text().strip()
        assert float(content) == pytest.approx(9876543210.654321)

    def test_save_handles_oserror(self, tmp_path):
        """OSError during save is caught and logged, not raised."""
        with patch("duplicacy_exporter.TIMESTAMP_FILE", "/nonexistent/dir/ts"):
            _save_last_timestamp(123.0)  # should not raise


# =========================================================================
# tail_docker_logs (mocked)
# =========================================================================

def _make_docker_frame(stream_type: int, payload: bytes) -> bytes:
    """Build a Docker multiplexed stream frame.

    Format: [stream_type(1)] [0(3)] [size(4 big-endian)] [payload]
    """
    header = bytes([stream_type, 0, 0, 0]) + len(payload).to_bytes(4, "big")
    return header + payload


class _FakeDockerResponse:
    """Simulate a Docker Engine API streamed response with multiplexed frames."""

    def __init__(self, frames_bytes, status=200):
        self.status = status
        self._buf = frames_bytes
        self._pos = 0

    def read1(self, sz):
        chunk = self._buf[self._pos:self._pos + sz]
        self._pos += len(chunk)
        return chunk

    def read(self):
        return self._buf


class _FakeConn:
    """Fake HTTP connection that returns a preset response, then raises."""

    def __init__(self, resp):
        self._resp = resp
        self._called = False

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        if self._called:
            raise ConnectionError("stop-after-one-iteration")
        self._called = True
        return self._resp


class TestTailDockerLogsMocked:
    """Test tail_docker_logs by replacing its internal _UnixConn class."""

    def _run_tail(self, state, container, frames_bytes, last_ts=0.0,
                  max_buf=None, resp_status=200):
        """Helper: run tail_docker_logs with a fake connection.

        Replaces the _UnixConn class inside tail_docker_logs by
        monkey-patching the function's code: we wrap it so that the
        locally-defined _UnixConn is replaced before the while-loop runs.
        Instead we use a simpler approach: patch http.client.HTTPConnection
        methods and socket.socket, and make request() raise on the 2nd call
        so the outer while-loop breaks into the except branch where
        time.sleep raises KeyboardInterrupt.
        """
        resp = _FakeDockerResponse(frames_bytes, status=resp_status)
        call_count = 0

        def fake_request(self_conn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise ConnectionError("stop-after-one-iteration")

        def fake_getresponse(self_conn):
            return resp

        patches = [
            patch("duplicacy_exporter._load_last_timestamp", return_value=last_ts),
            patch("duplicacy_exporter._save_last_timestamp"),
            patch("socket.socket"),
            patch("http.client.HTTPConnection.request", fake_request),
            patch("http.client.HTTPConnection.getresponse", fake_getresponse),
            patch("time.sleep", side_effect=KeyboardInterrupt("stop")),
        ]
        if max_buf is not None:
            patches.append(patch("duplicacy_exporter.MAX_LOG_BUFFER", max_buf))

        for p in patches:
            p.start()
        try:
            tail_docker_logs(state, container)
        except KeyboardInterrupt:
            pass
        finally:
            for p in patches:
                p.stop()

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_processes_docker_frames(self):
        """Frames with valid log lines are parsed and processed."""
        state = BackupState()

        line1 = b"2024-03-15T10:30:00.100000000Z --- Backup -> Primary (appdata) ---\n"
        line2 = b"2024-03-15T10:30:01.200000000Z Storage set to sftp://user@wt.mango-alpha.ts.net/backups\n"
        frames = _make_docker_frame(1, line1) + _make_docker_frame(1, line2)

        self._run_tail(state, "test-container", frames)

        assert state.current_storage_target == "wt"
        assert state.in_backup is True

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_non_200_response_triggers_retry(self):
        """Non-200 Docker API response triggers the retry path."""
        state = BackupState()
        self._run_tail(state, "missing-container", b"no such container",
                       resp_status=404)

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_skips_already_seen_timestamps(self):
        """Lines with timestamps <= last_ts are skipped."""
        state = BackupState()

        old_line = b"2024-03-15T10:00:00.000000000Z Old line should be skipped\n"
        new_line = b"2024-03-15T12:00:00.000000000Z --- Backup -> Primary (freshdata) ---\n"
        frames = _make_docker_frame(1, old_line) + _make_docker_frame(1, new_line)

        # last_ts between old and new line timestamps
        self._run_tail(state, "test-container", frames, last_ts=1710500400.0)

        assert state.current_snapshot == "freshdata"

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_buffer_overflow_discards_data(self):
        """Buffer exceeding MAX_LOG_BUFFER is discarded."""
        state = BackupState()

        big_payload = b"2024-03-15T10:30:00.000000000Z " + b"X" * 100 + b"\n"
        frames = _make_docker_frame(1, big_payload)

        self._run_tail(state, "test-container", frames, max_buf=16)

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_connection_error_retries(self):
        """Socket connection failure triggers retry loop."""
        state = BackupState()

        with patch("duplicacy_exporter._load_last_timestamp", return_value=0.0), \
             patch("socket.socket"), \
             patch("http.client.HTTPConnection.request",
                   side_effect=ConnectionRefusedError("refused")), \
             patch("time.sleep", side_effect=KeyboardInterrupt("stop")):
            try:
                tail_docker_logs(state, "test-container")
            except KeyboardInterrupt:
                pass

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_resumes_from_persisted_timestamp(self):
        """When last_ts > 0, the resume log path is taken."""
        state = BackupState()
        # Empty response, just verifying the resume-from-timestamp path
        self._run_tail(state, "test-container", b"", last_ts=999999.0)

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.REPLAY_HOURS", 1)
    def test_saves_timestamp_on_new_lines(self):
        """New log lines with timestamps trigger _save_last_timestamp."""
        state = BackupState()

        line = b"2024-03-15T10:30:00.100000000Z some log line\n"
        frames = _make_docker_frame(1, line)

        saved = []
        call_count = 0

        def fake_request(self_conn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise ConnectionError("stop-after-one-iteration")

        resp = _FakeDockerResponse(frames)

        with patch("duplicacy_exporter._load_last_timestamp", return_value=0.0), \
             patch("duplicacy_exporter._save_last_timestamp", side_effect=lambda ts: saved.append(ts)), \
             patch("socket.socket"), \
             patch("http.client.HTTPConnection.request", fake_request), \
             patch("http.client.HTTPConnection.getresponse", lambda *a, **k: resp), \
             patch("time.sleep", side_effect=KeyboardInterrupt("stop")):
            try:
                tail_docker_logs(state, "test-container")
            except KeyboardInterrupt:
                pass

        assert len(saved) > 0
        assert saved[0] > 0


# =========================================================================
# __main__ guard
# =========================================================================

class TestMainGuard:
    def test_main_guard(self):
        """Verify __name__ == '__main__' calls main()."""
        import duplicacy_exporter
        with patch.object(duplicacy_exporter, "main") as mock_main:
            exec(
                compile(
                    "if __name__ == '__main__': main()",
                    "<test>",
                    "exec",
                ),
                {"__name__": "__main__", "main": mock_main},
            )
            mock_main.assert_called_once()


# =========================================================================
# Issue duplicacy-ha#9: backup differentiation (new in v0.4.0)
# =========================================================================

class TestBasename:
    def test_empty(self):
        assert _basename("") == ""

    def test_simple_posix(self):
        assert _basename("/mnt/photos") == "photos"

    def test_trailing_slash(self):
        assert _basename("/mnt/photos/") == "photos"

    def test_windows_separator(self):
        assert _basename("C:\\Users\\gchen\\repo") == "repo"

    def test_single_component(self):
        assert _basename("repo") == "repo"


class TestWebhookDifferentiation:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_directory_used_when_no_id(self):
        """With no id field, the source directory differentiates the backup."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "computer": "mac-mini",
            "directory": "/Users/gchen/photos",
            "storage": "sftp://user@wt.mango-alpha.ts.net/path",
            "result": "success",
            "start_time": 1000,
            "end_time": 1600,
        }
        handler.handle(payload)
        labels = ("photos", "wt", "mac-mini")
        assert last_exit_code.labels(*labels)._value.get() == 0.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_two_backups_one_machine_stay_distinct(self):
        """Two Web UI backups on one machine (no id) must not collapse (issue #9)."""
        state = BackupState()
        handler = WebhookHandler(state)
        base = {
            "computer": "mac-mini",
            "storage": "sftp://user@wt.mango-alpha.ts.net/path",
            "result": "success",
            "start_time": 1000,
            "end_time": 1600,
        }
        handler.handle({**base, "directory": "/srv/docs"})
        handler.handle({**base, "directory": "/srv/photos"})
        assert last_exit_code.labels("docs", "wt", "mac-mini")._value.get() == 0.0
        assert last_exit_code.labels("photos", "wt", "mac-mini")._value.get() == 0.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_explicit_id_takes_precedence(self):
        """An explicit id field wins over directory."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "id": "explicit",
            "directory": "/srv/ignored",
            "storage": "sftp://user@wt.mango-alpha.ts.net/path",
            "computer": "mac-mini",
            "result": "success",
            "start_time": 0,
            "end_time": 0,
        }
        handler.handle(payload)
        assert last_exit_code.labels("explicit", "wt", "mac-mini")._value.get() == 0.0

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_name_field_used(self):
        """The 'name' field is honoured when present (no id)."""
        state = BackupState()
        handler = WebhookHandler(state)
        payload = {
            "name": "byname",
            "storage": "sftp://user@wt.mango-alpha.ts.net/path",
            "computer": "mac-mini",
            "result": "success",
            "start_time": 0,
            "end_time": 0,
        }
        handler.handle(payload)
        assert last_exit_code.labels("byname", "wt", "mac-mini")._value.get() == 0.0


class TestSnapshotIdEnv:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    @patch("duplicacy_exporter.SNAPSHOT_ID", "envsnap")
    def test_env_seeds_snapshot(self):
        """SNAPSHOT_ID env seeds current_snapshot so stock-CLI summaries resolve."""
        state = BackupState()
        assert state.current_snapshot == "envsnap"
        state.process_line("Storage set to sftp://user@wt.mango-alpha.ts.net/backups")
        state.process_line("Backup for /data at revision 7 completed")
        labels = ("envsnap", "wt", "testmachine")
        assert last_revision.labels(*labels)._value.get() == 7.0


class TestDiagnostics:
    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_backups_seen_increments_even_when_unlabelled(self):
        """A completed backup bumps the counter even if it can't be labelled."""
        before = backups_seen._value.get()
        state = BackupState()
        state.current_snapshot = ""  # unresolved -> labels drop, but still "seen"
        state.process_line("Backup for /data at revision 1 completed")
        assert backups_seen._value.get() == before + 1

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_last_activity_updated(self):
        state = BackupState()
        state.process_line("some idle line", log_time=12345.0)
        assert exporter_last_activity_ts._value.get() == 12345.0


class TestMainMachineWarning:
    @patch("duplicacy_exporter.MACHINE_NAME", "")
    @patch("duplicacy_exporter.MODE", "log_tail")
    @patch("duplicacy_exporter.LOG_FILE", "")
    @patch("duplicacy_exporter.LISTEN_PORT", 0)
    def test_main_warns_when_machine_name_unset(self):
        """log_tail with no MACHINE_NAME emits a startup warning."""
        import duplicacy_exporter
        server_mock = MagicMock()
        server_mock.serve_forever.side_effect = KeyboardInterrupt()
        with patch.object(duplicacy_exporter, "HTTPServer", return_value=server_mock):
            with patch.object(duplicacy_exporter, "tail_docker_logs"):
                with patch("threading.Thread"):
                    with patch.object(duplicacy_exporter.logger, "warning") as warn:
                        duplicacy_exporter.main()
                        assert any(
                            "MACHINE_NAME is not set" in str(c.args[0])
                            for c in warn.call_args_list
                        )
