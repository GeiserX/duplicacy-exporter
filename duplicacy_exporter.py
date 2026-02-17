"""
Duplicacy Prometheus Exporter

Exports real-time and summary backup metrics from Duplicacy CLI or Web UI.

Modes:
  - log_tail: Tails Docker container logs (or a log file) for real-time metrics
  - webhook:  Receives POST from Duplicacy Web UI report_url
"""

import json
import logging
import os
import re
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Counter,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODE = os.getenv("MODE", "log_tail")  # log_tail | webhook
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "9750"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DOCKER_CONTAINER_NAME = os.getenv("DOCKER_CONTAINER_NAME", "duplicacy-cli-cron")
LOG_FILE = os.getenv("LOG_FILE", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("duplicacy-exporter")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

registry = CollectorRegistry()

EXPORTER_INFO = Info(
    "duplicacy_exporter",
    "Duplicacy exporter metadata",
    registry=registry,
)
EXPORTER_INFO.info({"version": "0.1.0", "mode": MODE})

# Labels applied to every backup metric
LABEL_NAMES = ["snapshot_id", "storage_name", "machine"]

# Real-time gauges (updated per chunk line)
backup_running = Gauge(
    "duplicacy_backup_running",
    "Whether a backup is currently in progress (1=running, 0=idle)",
    LABEL_NAMES,
    registry=registry,
)
backup_speed_bps = Gauge(
    "duplicacy_backup_speed_bytes_per_second",
    "Current backup speed in bytes per second",
    LABEL_NAMES,
    registry=registry,
)
backup_progress = Gauge(
    "duplicacy_backup_progress_ratio",
    "Backup progress from 0.0 to 1.0",
    LABEL_NAMES,
    registry=registry,
)
backup_chunks_uploaded = Gauge(
    "duplicacy_backup_chunks_uploaded",
    "Number of chunks uploaded in the current/last backup",
    LABEL_NAMES,
    registry=registry,
)
backup_chunks_skipped = Gauge(
    "duplicacy_backup_chunks_skipped",
    "Number of chunks skipped in the current/last backup",
    LABEL_NAMES,
    registry=registry,
)

# Post-run summary gauges
last_success_ts = Gauge(
    "duplicacy_backup_last_success_timestamp_seconds",
    "Unix timestamp of the last successful backup completion",
    LABEL_NAMES,
    registry=registry,
)
last_duration = Gauge(
    "duplicacy_backup_last_duration_seconds",
    "Duration of the last completed backup in seconds",
    LABEL_NAMES,
    registry=registry,
)
last_files_total = Gauge(
    "duplicacy_backup_last_files_total",
    "Total number of files in the last backup",
    LABEL_NAMES,
    registry=registry,
)
last_files_new = Gauge(
    "duplicacy_backup_last_files_new",
    "Number of new files in the last backup",
    LABEL_NAMES,
    registry=registry,
)
last_bytes_uploaded = Gauge(
    "duplicacy_backup_last_bytes_uploaded",
    "Bytes uploaded in the last backup",
    LABEL_NAMES,
    registry=registry,
)
last_bytes_new = Gauge(
    "duplicacy_backup_last_bytes_new",
    "New bytes (before upload/compression) in the last backup",
    LABEL_NAMES,
    registry=registry,
)
last_chunks_new = Gauge(
    "duplicacy_backup_last_chunks_new",
    "New chunks in the last backup",
    LABEL_NAMES,
    registry=registry,
)
last_exit_code = Gauge(
    "duplicacy_backup_last_exit_code",
    "Exit code of the last backup (0=success, 1=failure)",
    LABEL_NAMES,
    registry=registry,
)
last_revision = Gauge(
    "duplicacy_backup_last_revision",
    "Revision number of the last completed backup",
    LABEL_NAMES,
    registry=registry,
)

# Totals counter (monotonically increasing across all runs)
total_bytes_uploaded = Counter(
    "duplicacy_backup_bytes_uploaded_total",
    "Total bytes uploaded across all backup runs",
    LABEL_NAMES,
    registry=registry,
)

# Prune metrics
prune_running = Gauge(
    "duplicacy_prune_running",
    "Whether a prune is currently in progress",
    LABEL_NAMES,
    registry=registry,
)
last_prune_success_ts = Gauge(
    "duplicacy_prune_last_success_timestamp_seconds",
    "Unix timestamp of the last successful prune",
    LABEL_NAMES,
    registry=registry,
)

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# "Uploaded chunk 4062 size 14940431, 1.24MB/s 21 days 16:40:28 0.8%"
# "Skipped chunk 261376 size 1048576, 65.18MB/s 03:05:12 29.2%"
RE_CHUNK_LINE = re.compile(
    r"(?P<action>Uploaded|Skipped) chunk (?P<chunk_num>\d+) "
    r"size (?P<size>\d+), "
    r"(?P<speed>[\d.]+)(?P<speed_unit>[KMG]?B/s) "
    r"(?:(?P<days>\d+) days? )?(?P<eta>\d{2}:\d{2}:\d{2}) "
    r"(?P<progress>[\d.]+)%"
)

# "Storage set to minio://garage@192.168.10.100:9000/duplicacy/WatchTower/Multimedia"
RE_STORAGE_SET = re.compile(
    r"Storage set to (?P<storage_url>\S+)"
)

# "Backup for /path at revision 124 completed"
RE_BACKUP_END = re.compile(
    r"Backup for (?P<path>\S+) at revision (?P<revision>\d+) completed"
)

# "BACKUP_STATS Files: 2682641 total, 8530G bytes; 881 new, 15,666M bytes"
RE_STATS_FILES = re.compile(
    r"Files:\s*(?P<total>[\d,]+)\s*total,\s*(?P<total_bytes>[\d,.]+)(?P<total_unit>[KMG]?)\s*bytes;\s*"
    r"(?P<new>[\d,]+)\s*new,\s*(?P<new_bytes>[\d,.]+)(?P<new_unit>[KMG]?)\s*bytes"
)

# "BACKUP_STATS All chunks: 1865958 total, 8534G bytes; 2945 new, 14,784M bytes, 14,648M bytes uploaded"
RE_STATS_CHUNKS = re.compile(
    r"All chunks:\s*(?P<total>[\d,]+)\s*total,\s*(?P<total_bytes>[\d,.]+)(?P<total_unit>[KMG]?)\s*bytes;\s*"
    r"(?P<new>[\d,]+)\s*new,\s*(?P<new_bytes>[\d,.]+)(?P<new_unit>[KMG]?)\s*bytes,\s*"
    r"(?P<uploaded_bytes>[\d,.]+)(?P<uploaded_unit>[KMG]?)\s*bytes uploaded"
)

# "BACKUP_STATS Total running time: 00:57:56"
RE_STATS_TIME = re.compile(
    r"Total running time:\s*(?:(?P<days>\d+):)?(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})"
)

# Script header pattern: "--- Backup Output ---"
RE_SECTION_HEADER = re.compile(r"^---\s*(.+?)\s*---$")

# Snapshot ID from duplicacy init line or preferences
# The executor script sets SNAPSHOTID and STORAGENAME as shell vars
# We detect the storage from "Storage set to" and snapshot from backup completion


def _parse_size(value_str: str, unit: str) -> float:
    """Convert a value+unit like '14,648' + 'M' to bytes."""
    value = float(value_str.replace(",", ""))
    multipliers = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return value * multipliers.get(unit, 1)


def _parse_speed(speed_str: str, unit: str) -> float:
    """Convert speed string + unit to bytes/second."""
    speed = float(speed_str)
    multipliers = {"B/s": 1, "KB/s": 1024, "MB/s": 1024 ** 2, "GB/s": 1024 ** 3}
    return speed * multipliers.get(unit, 1)


def _parse_duration(days: str, hours: str, minutes: str, seconds: str) -> float:
    """Convert time components to total seconds."""
    d = int(days) if days else 0
    return d * 86400 + int(hours) * 3600 + int(minutes) * 60 + int(seconds)


# ---------------------------------------------------------------------------
# Backup state tracker
# ---------------------------------------------------------------------------

class BackupState:
    """Tracks state per snapshot across log lines."""

    def __init__(self):
        self.lock = threading.Lock()
        # Current run context
        self.current_storage = ""
        self.current_snapshot = ""
        self.current_machine = os.getenv("MACHINE_NAME", "")
        self.in_backup = False
        self.in_prune = False
        self.uploaded_count = 0
        self.skipped_count = 0

    def _labels(self, snapshot_id: str = "", storage: str = "", machine: str = "") -> tuple:
        sid = snapshot_id or self.current_snapshot or "unknown"
        sto = storage or self.current_storage or "unknown"
        mach = machine or self.current_machine or "unknown"
        return (sid, sto, mach)

    def process_line(self, line: str):
        """Parse a single log line and update metrics."""
        line = line.strip()
        if not line:
            return

        with self.lock:
            self._process_line_inner(line)

    def _process_line_inner(self, line: str):
        # Section headers from executor script
        header = RE_SECTION_HEADER.match(line)
        if header:
            section = header.group(1).lower()
            if "backup" in section:
                self.in_backup = True
                self.in_prune = False
                self.uploaded_count = 0
                self.skipped_count = 0
                labels = self._labels()
                backup_running.labels(*labels).set(1)
                backup_progress.labels(*labels).set(0)
                backup_speed_bps.labels(*labels).set(0)
                backup_chunks_uploaded.labels(*labels).set(0)
                backup_chunks_skipped.labels(*labels).set(0)
                logger.info("Backup section started")
            elif "prune" in section:
                self.in_backup = False
                self.in_prune = True
                labels = self._labels()
                prune_running.labels(*labels).set(1)
                backup_running.labels(*labels).set(0)
                logger.info("Prune section started")
            return

        # Storage URL
        m = RE_STORAGE_SET.search(line)
        if m:
            self.current_storage = m.group("storage_url")
            logger.debug("Storage set to %s", self.current_storage)
            return

        # Chunk upload/skip line (real-time progress)
        m = RE_CHUNK_LINE.search(line)
        if m:
            labels = self._labels()
            action = m.group("action")

            if action == "Uploaded":
                self.uploaded_count += 1
                backup_chunks_uploaded.labels(*labels).set(self.uploaded_count)
            else:
                self.skipped_count += 1
                backup_chunks_skipped.labels(*labels).set(self.skipped_count)

            speed = _parse_speed(m.group("speed"), m.group("speed_unit"))
            backup_speed_bps.labels(*labels).set(speed)

            progress = float(m.group("progress")) / 100.0
            backup_progress.labels(*labels).set(progress)
            return

        # Backup completed
        m = RE_BACKUP_END.search(line)
        if m:
            labels = self._labels()
            revision = int(m.group("revision"))
            backup_running.labels(*labels).set(0)
            backup_progress.labels(*labels).set(1.0)
            backup_speed_bps.labels(*labels).set(0)
            last_success_ts.labels(*labels).set(time.time())
            last_exit_code.labels(*labels).set(0)
            last_revision.labels(*labels).set(revision)
            self.in_backup = False
            logger.info("Backup completed at revision %d", revision)
            return

        # BACKUP_STATS Files line
        m = RE_STATS_FILES.search(line)
        if m:
            labels = self._labels()
            last_files_total.labels(*labels).set(int(m.group("total").replace(",", "")))
            last_files_new.labels(*labels).set(int(m.group("new").replace(",", "")))
            new_bytes = _parse_size(m.group("new_bytes"), m.group("new_unit"))
            last_bytes_new.labels(*labels).set(new_bytes)
            return

        # BACKUP_STATS All chunks line
        m = RE_STATS_CHUNKS.search(line)
        if m:
            labels = self._labels()
            uploaded = _parse_size(m.group("uploaded_bytes"), m.group("uploaded_unit"))
            last_bytes_uploaded.labels(*labels).set(uploaded)
            last_chunks_new.labels(*labels).set(int(m.group("new").replace(",", "")))
            total_bytes_uploaded.labels(*labels).inc(uploaded)
            return

        # BACKUP_STATS Total running time
        m = RE_STATS_TIME.search(line)
        if m:
            labels = self._labels()
            duration = _parse_duration(
                m.group("days"), m.group("hours"), m.group("minutes"), m.group("seconds")
            )
            last_duration.labels(*labels).set(duration)
            return

        # Detect backup failure from executor script
        if "Backup failed" in line or "backup failed" in line:
            labels = self._labels()
            backup_running.labels(*labels).set(0)
            last_exit_code.labels(*labels).set(1)
            self.in_backup = False
            logger.warning("Backup failure detected")
            return

        # Prune completion
        if self.in_prune and ("Prune completed" in line or "completed" in line.lower()):
            if "successfully" in line.lower() or "prune completed" in line.lower():
                labels = self._labels()
                prune_running.labels(*labels).set(0)
                last_prune_success_ts.labels(*labels).set(time.time())
                self.in_prune = False
                logger.info("Prune completed")
                return

        # Notification line to extract snapshot ID / machine name
        # "🟢 *machinename* — _snapshotid_"
        if "—" in line and "*" in line:
            parts = line.split("—")
            if len(parts) >= 2:
                machine_part = parts[0].strip().strip("🟢⏭️⚠️").strip()
                snapshot_part = parts[1].strip()
                # Extract between * markers
                machine_match = re.search(r"\*(.+?)\*", machine_part)
                snapshot_match = re.search(r"_(.+?)_", snapshot_part)
                if machine_match:
                    self.current_machine = machine_match.group(1)
                if snapshot_match:
                    self.current_snapshot = snapshot_match.group(1)
                logger.debug(
                    "Detected machine=%s snapshot=%s",
                    self.current_machine,
                    self.current_snapshot,
                )


# ---------------------------------------------------------------------------
# Webhook handler (for Duplicacy Web UI report_url)
# ---------------------------------------------------------------------------

class WebhookHandler:
    """Processes JSON payloads from Duplicacy Web UI."""

    def __init__(self, state: BackupState):
        self.state = state

    def handle(self, payload: dict):
        """Process a report_url JSON payload from Duplicacy Web UI."""
        snapshot_id = payload.get("id", payload.get("computer", "unknown"))
        storage = payload.get("storage", payload.get("storage_url", "unknown"))
        machine = payload.get("computer", os.getenv("MACHINE_NAME", "unknown"))
        labels = (snapshot_id, storage, machine)

        result = payload.get("result", "")
        exit_code = 0 if result.lower() == "success" else 1
        last_exit_code.labels(*labels).set(exit_code)

        if exit_code == 0:
            last_success_ts.labels(*labels).set(time.time())

        # Duration
        start_time = payload.get("start_time", 0)
        end_time = payload.get("end_time", 0)
        if start_time and end_time:
            last_duration.labels(*labels).set(end_time - start_time)

        # Files
        last_files_total.labels(*labels).set(payload.get("total_files", 0))
        last_files_new.labels(*labels).set(payload.get("new_files", 0))

        # Chunks
        last_chunks_new.labels(*labels).set(payload.get("new_chunks", 0))

        # Bytes
        uploaded = payload.get("uploaded_chunk_size", 0)
        last_bytes_uploaded.labels(*labels).set(uploaded)
        last_bytes_new.labels(*labels).set(payload.get("new_file_size", 0))
        if uploaded > 0:
            total_bytes_uploaded.labels(*labels).inc(uploaded)

        # Compute average speed if we have duration
        duration = end_time - start_time if (start_time and end_time) else 0
        if duration > 0 and uploaded > 0:
            backup_speed_bps.labels(*labels).set(uploaded / duration)

        backup_running.labels(*labels).set(0)
        backup_progress.labels(*labels).set(1.0)

        logger.info(
            "Webhook: %s result=%s uploaded=%d duration=%ds",
            snapshot_id, result, uploaded, duration,
        )


# ---------------------------------------------------------------------------
# HTTP server (serves /metrics and optionally /webhook)
# ---------------------------------------------------------------------------

class MetricsHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for /metrics and /webhook endpoints."""

    webhook_handler = None  # Set by main()

    def do_GET(self):
        if self.path == "/metrics":
            output = generate_latest(registry)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(output)
        elif self.path == "/health" or self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK\n")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == WEBHOOK_PATH and self.webhook_handler:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body)
                self.webhook_handler.handle(payload)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK\n")
            except (json.JSONDecodeError, Exception) as exc:
                logger.error("Webhook error: %s", exc)
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(exc).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default access logging to avoid noise."""
        pass


# ---------------------------------------------------------------------------
# Log tail mode: Docker container logs
# ---------------------------------------------------------------------------

def tail_docker_logs(state: BackupState, container_name: str):
    """Tail Docker container logs via the Docker Engine API over Unix socket.

    Uses only Python stdlib (no docker SDK) to minimise image size and RAM.
    """
    import http.client
    import socket as _socket

    class _UnixConn(http.client.HTTPConnection):
        def __init__(self, sock_path):
            super().__init__("localhost")
            self._sock_path = sock_path

        def connect(self):
            self.sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            self.sock.connect(self._sock_path)

    sock_path = os.getenv("DOCKER_HOST", "/var/run/docker.sock")
    logger.info("Tailing logs from container %s via %s", container_name, sock_path)

    while True:
        try:
            conn = _UnixConn(sock_path)
            since = int(time.time())
            conn.request(
                "GET",
                f"/containers/{container_name}/logs"
                f"?follow=true&stdout=true&stderr=true&since={since}",
            )
            resp = conn.getresponse()
            if resp.status != 200:
                body = resp.read().decode(errors="replace")
                raise RuntimeError(f"Docker API {resp.status}: {body}")

            buf = b""
            while True:
                chunk = resp.read1(4096)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 8:
                    frame_size = int.from_bytes(buf[4:8], "big")
                    total = 8 + frame_size
                    if len(buf) < total:
                        break
                    payload = buf[8:total].decode("utf-8", errors="replace")
                    buf = buf[total:]
                    for subline in payload.rstrip("\n").split("\n"):
                        if subline:
                            state.process_line(subline)
        except Exception as exc:
            logger.warning("Docker log tail error (will retry in 10s): %s", exc)
            time.sleep(10)


# ---------------------------------------------------------------------------
# Log tail mode: Log file
# ---------------------------------------------------------------------------

def tail_log_file(state: BackupState, file_path: str):
    """Tail a log file, following new lines as they are written."""
    logger.info("Tailing log file: %s", file_path)

    while True:
        try:
            with open(file_path, "r") as f:
                # Seek to end
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        state.process_line(line)
                    else:
                        time.sleep(0.5)
        except FileNotFoundError:
            logger.warning("Log file %s not found, retrying in 10s...", file_path)
            time.sleep(10)
        except Exception as exc:
            logger.warning("Log file tail error (retrying in 10s): %s", exc)
            time.sleep(10)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting duplicacy-exporter v0.1.0 (mode=%s, port=%d)", MODE, LISTEN_PORT)

    state = BackupState()

    # Start log tailing thread if in log_tail mode
    if MODE == "log_tail":
        if LOG_FILE:
            tailer = threading.Thread(
                target=tail_log_file, args=(state, LOG_FILE), daemon=True
            )
        else:
            tailer = threading.Thread(
                target=tail_docker_logs,
                args=(state, DOCKER_CONTAINER_NAME),
                daemon=True,
            )
        tailer.start()
        logger.info("Log tailer thread started")

    # Set up webhook handler if in webhook mode (or both)
    webhook = WebhookHandler(state)
    MetricsHTTPHandler.webhook_handler = webhook if MODE == "webhook" else None

    # Also accept webhooks in log_tail mode (hybrid)
    if MODE == "log_tail":
        MetricsHTTPHandler.webhook_handler = webhook

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), MetricsHTTPHandler)
    logger.info("Serving metrics on http://0.0.0.0:%d/metrics", LISTEN_PORT)
    if MODE == "webhook" or MODE == "log_tail":
        logger.info("Webhook endpoint available at http://0.0.0.0:%d%s", LISTEN_PORT, WEBHOOK_PATH)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
