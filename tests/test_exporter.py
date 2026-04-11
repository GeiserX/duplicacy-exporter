"""Tests for duplicacy-exporter parsing and state management."""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from duplicacy_exporter import (
    _extract_storage_target,
    _parse_size,
    _parse_speed,
    _parse_duration,
    _parse_docker_timestamp,
    BackupState,
    RE_CHUNK_LINE,
    RE_STORAGE_SET,
    RE_BACKUP_END,
    RE_STATS_FILES,
    RE_STATS_CHUNKS,
    RE_STATS_TIME,
    RE_SECTION_HEADER,
    RE_META_LINE,
)


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


class TestParseSpeed:
    def test_bytes_per_second(self):
        assert _parse_speed("100", "B/s") == 100.0

    def test_kb_per_second(self):
        assert _parse_speed("5", "KB/s") == 5 * 1024

    def test_mb_per_second(self):
        assert _parse_speed("10.5", "MB/s") == 10.5 * 1024 ** 2


class TestParseDuration:
    def test_hours_minutes_seconds(self):
        assert _parse_duration(None, "01", "30", "45") == 3600 + 1800 + 45

    def test_with_days(self):
        assert _parse_duration("2", "03", "00", "00") == 2 * 86400 + 3 * 3600

    def test_zero_duration(self):
        assert _parse_duration(None, "00", "00", "00") == 0


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

    def test_stats_time(self):
        line = "Total running time: 01:23:45"
        m = RE_STATS_TIME.search(line)
        assert m is not None
        assert m.group("hours") == "01"
        assert m.group("minutes") == "23"
        assert m.group("seconds") == "45"

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

    def test_meta_line(self):
        line = "DUPLICACY_META snapshot_id=appdata direction=primary"
        m = RE_META_LINE.match(line)
        assert m is not None
        assert "snapshot_id=appdata" in m.group("kvpairs")


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
    def test_prune_completion(self):
        state = BackupState()
        state.current_storage_target = "watchtower"
        state.in_prune = True
        state.process_line("All fossil collections have been removed")
        assert state.in_prune is False

    @patch("duplicacy_exporter.MACHINE_NAME", "testmachine")
    def test_meta_line_sets_snapshot(self):
        state = BackupState()
        state.process_line("DUPLICACY_META snapshot_id=mydata direction=primary")
        assert state.current_snapshot == "mydata"
