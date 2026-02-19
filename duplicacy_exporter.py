"""
Duplicacy Prometheus Exporter v0.3.0

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

VERSION = "0.3.0"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODE = os.getenv("MODE", "log_tail")  # log_tail | webhook
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "9750"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DOCKER_CONTAINER_NAME = os.getenv("DOCKER_CONTAINER_NAME", "duplicacy-cli-cron")
LOG_FILE = os.getenv("LOG_FILE", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
MACHINE_NAME = os.getenv("MACHINE_NAME", "")
TAILSCALE_DOMAIN = os.getenv("TAILSCALE_DOMAIN", "mango-alpha.ts.net")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("duplicacy-exporter")

# ---------------------------------------------------------------------------
# Storage host mapping
# ---------------------------------------------------------------------------

def _load_storage_host_map() -> dict:
    """Parse STORAGE_HOST_MAP env var: JSON mapping hostname/IP -> display name.

    Example: {"192.168.10.100": "watchtower", "192.168.20.5": "geiserct"}
    """
    raw = os.getenv("STORAGE_HOST_MAP", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid STORAGE_HOST_MAP JSON, ignoring")
        return {}

_STORAGE_HOST_MAP = _load_storage_host_map()


def _extract_storage_target(url: str) -> str:
    """Derive a human-readable target name from a storage URL.

    minio://garage@watchtower.mango-alpha.ts.net:9000/... -> watchtower
    sftp://user@geiserct.mango-alpha.ts.net/...           -> geiserct
    minio://garage@192.168.10.100:9000/...                -> (via STORAGE_HOST_MAP)
    """
    m = re.search(r"@([^:/]+)", url)
    if not m:
        m = re.search(r"://([^:/]+)", url)
    if not m:
        return url

    host = m.group(1)

    if host in _STORAGE_HOST_MAP:
        return _STORAGE_HOST_MAP[host]

    ts_suffix = f".{TAILSCALE_DOMAIN}"
    if host.endswith(ts_suffix):
        return host[: -len(ts_suffix)]

    if "." in host and not host.replace(".", "").isdigit():
        return host.split(".")[0]

    return host

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

registry = CollectorRegistry()

EXPORTER_INFO = Info(
    "duplicacy_exporter",
    "Duplicacy exporter metadata",
    registry=registry,
)
EXPORTER_INFO.info({"version": VERSION, "mode": MODE})

BACKUP_LABELS = ["snapshot_id", "storage_target", "machine"]
PRUNE_LABELS = ["storage_target", "machine"]

backup_running = Gauge(
    "duplicacy_backup_running",
    "Whether a backup is currently in progress (1=running, 0=idle)",
    BACKUP_LABELS, registry=registry,
)
backup_speed_bps = Gauge(
    "duplicacy_backup_speed_bytes_per_second",
    "Current backup speed in bytes per second",
    BACKUP_LABELS, registry=registry,
)
backup_progress = Gauge(
    "duplicacy_backup_progress_ratio",
    "Backup progress from 0.0 to 1.0",
    BACKUP_LABELS, registry=registry,
)
backup_chunks_uploaded = Gauge(
    "duplicacy_backup_chunks_uploaded",
    "Chunks uploaded in the current backup run",
    BACKUP_LABELS, registry=registry,
)
backup_chunks_skipped = Gauge(
    "duplicacy_backup_chunks_skipped",
    "Chunks skipped in the current backup run",
    BACKUP_LABELS, registry=registry,
)

last_success_ts = Gauge(
    "duplicacy_backup_last_success_timestamp_seconds",
    "Unix timestamp of the last successful backup completion",
    BACKUP_LABELS, registry=registry,
)
last_duration = Gauge(
    "duplicacy_backup_last_duration_seconds",
    "Duration of the last completed backup in seconds",
    BACKUP_LABELS, registry=registry,
)
last_files_total = Gauge(
    "duplicacy_backup_last_files_total",
    "Total number of files in the last backup",
    BACKUP_LABELS, registry=registry,
)
last_files_new = Gauge(
    "duplicacy_backup_last_files_new",
    "Number of new files in the last backup",
    BACKUP_LABELS, registry=registry,
)
last_bytes_uploaded = Gauge(
    "duplicacy_backup_last_bytes_uploaded",
    "Bytes uploaded in the last backup",
    BACKUP_LABELS, registry=registry,
)
last_bytes_new = Gauge(
    "duplicacy_backup_last_bytes_new",
    "New bytes (before upload/compression) in the last backup",
    BACKUP_LABELS, registry=registry,
)
last_chunks_new = Gauge(
    "duplicacy_backup_last_chunks_new",
    "New chunks in the last backup",
    BACKUP_LABELS, registry=registry,
)
last_exit_code = Gauge(
    "duplicacy_backup_last_exit_code",
    "Exit code of the last backup (0=success, 1=failure)",
    BACKUP_LABELS, registry=registry,
)
last_revision = Gauge(
    "duplicacy_backup_last_revision",
    "Revision number of the last completed backup",
    BACKUP_LABELS, registry=registry,
)
total_bytes_uploaded = Counter(
    "duplicacy_backup_bytes_uploaded_total",
    "Total bytes uploaded across all backup runs",
    BACKUP_LABELS, registry=registry,
)

prune_running = Gauge(
    "duplicacy_prune_running",
    "Whether a prune is currently in progress",
    PRUNE_LABELS, registry=registry,
)
last_prune_success_ts = Gauge(
    "duplicacy_prune_last_success_timestamp_seconds",
    "Unix timestamp of the last successful prune",
    PRUNE_LABELS, registry=registry,
)

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

RE_CHUNK_LINE = re.compile(
    r"(?P<action>Uploaded|Skipped) chunk (?P<chunk_num>\d+) "
    r"size (?P<size>\d+), "
    r"(?P<speed>[\d.]+)(?P<speed_unit>[KMG]?B/s) "
    r"(?:(?P<days>\d+) days? )?(?P<eta>\d{2}:\d{2}:\d{2}) "
    r"(?P<progress>[\d.]+)%"
)

RE_STORAGE_SET = re.compile(r"Storage set to (?P<storage_url>\S+)")

RE_BACKUP_END = re.compile(
    r"Backup for (?P<path>\S+) at revision (?P<revision>\d+) completed"
)

RE_STATS_FILES = re.compile(
    r"Files:\s*(?P<total>[\d,]+)\s*total,\s*(?P<total_bytes>[\d,.]+)(?P<total_unit>[KMG]?)\s*bytes;\s*"
    r"(?P<new>[\d,]+)\s*new,\s*(?P<new_bytes>[\d,.]+)(?P<new_unit>[KMG]?)\s*bytes"
)

RE_STATS_CHUNKS = re.compile(
    r"All chunks:\s*(?P<total>[\d,]+)\s*total,\s*(?P<total_bytes>[\d,.]+)(?P<total_unit>[KMG]?)\s*bytes;\s*"
    r"(?P<new>[\d,]+)\s*new,\s*(?P<new_bytes>[\d,.]+)(?P<new_unit>[KMG]?)\s*bytes,\s*"
    r"(?P<uploaded_bytes>[\d,.]+)(?P<uploaded_unit>[KMG]?)\s*bytes uploaded"
)

RE_STATS_TIME = re.compile(
    r"Total running time:\s*(?:(?P<days>\d+):)?(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})"
)

# Section headers from dual-executor.sh:
#   "--- Backup -> Primary (appdata) ---"
#   "--- Backup -> Secondary (appdataC) ---"
#   "--- Prune Primary ---"
#   "--- Prune Secondary ---"
# Legacy: "--- Backup Output ---", "--- Prune Output ---"
RE_SECTION_HEADER = re.compile(
    r"^---\s*(?P<type>Backup|Prune)\s*"
    r"(?:->\s*)?(?P<direction>Primary|Secondary|Output)"
    r"(?:\s*\((?P<storage>\w+)\))?\s*---$"
)

# Structured metadata marker (from enhanced dual-executor.sh):
#   "DUPLICACY_META snapshot_id=appdata direction=primary"
RE_META_LINE = re.compile(r"^DUPLICACY_META\s+(?P<kvpairs>.+)$")

_PRUNE_COMPLETION_PATTERNS = [
    "all fossil collections have been removed",
    "no snapshot to delete",
    "prune completed",
    "nothing to prune",
]


def _parse_size(value_str: str, unit: str) -> float:
    value = float(value_str.replace(",", ""))
    multipliers = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return value * multipliers.get(unit, 1)


def _parse_speed(speed_str: str, unit: str) -> float:
    speed = float(speed_str)
    multipliers = {"B/s": 1, "KB/s": 1024, "MB/s": 1024 ** 2, "GB/s": 1024 ** 3}
    return speed * multipliers.get(unit, 1)


def _parse_duration(days: str, hours: str, minutes: str, seconds: str) -> float:
    d = int(days) if days else 0
    return d * 86400 + int(hours) * 3600 + int(minutes) * 60 + int(seconds)


# ---------------------------------------------------------------------------
# Backup state tracker
# ---------------------------------------------------------------------------

class BackupState:
    """Tracks backup/prune state across log lines with correct label resolution.

    Labels are only emitted after BOTH the section header (snapshot_id) AND
    the "Storage set to" line (storage_target) have been parsed, preventing
    the label-drift problem where stale values from previous sections leaked
    into new metric series.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.machine = MACHINE_NAME
        self.current_snapshot = ""
        self.current_storage_target = ""
        self.in_backup = False
        self.in_prune = False
        self.uploaded_count = 0
        self.skipped_count = 0

    def _backup_labels(self) -> tuple | None:
        sid = self.current_snapshot
        tgt = self.current_storage_target
        mach = self.machine
        if not sid or not tgt or not mach:
            return None
        return (sid, tgt, mach)

    def _prune_labels(self) -> tuple | None:
        tgt = self.current_storage_target
        mach = self.machine
        if not tgt or not mach:
            return None
        return (tgt, mach)

    def _end_active_prune(self):
        """End prune section on transition (sets running=0 but not success ts)."""
        if self.in_prune:
            pl = self._prune_labels()
            if pl:
                prune_running.labels(*pl).set(0)
        self.in_prune = False

    def process_line(self, line: str):
        line = line.strip()
        if not line:
            return
        with self.lock:
            self._process_line_inner(line)

    def _process_line_inner(self, line: str):

        # --- Structured metadata marker ---
        m = RE_META_LINE.match(line)
        if m:
            for kv in m.group("kvpairs").split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k == "snapshot_id":
                        self.current_snapshot = v
                    elif k == "storage_target":
                        self.current_storage_target = v
                    elif k == "machine":
                        self.machine = v
            logger.debug("META: snapshot=%s target=%s",
                         self.current_snapshot, self.current_storage_target)
            return

        # --- Section headers ---
        header = RE_SECTION_HEADER.match(line)
        if header:
            sec_type = header.group("type").lower()
            direction = header.group("direction").lower()
            storage_name = header.group("storage") or ""

            if sec_type == "backup":
                self._end_active_prune()

                self.in_backup = True
                self.in_prune = False
                self.uploaded_count = 0
                self.skipped_count = 0
                self.current_storage_target = ""

                if storage_name:
                    if direction == "secondary" and storage_name.endswith("C"):
                        self.current_snapshot = storage_name[:-1]
                    else:
                        self.current_snapshot = storage_name

                logger.info("Backup section: %s (%s) snapshot=%s",
                            direction, storage_name, self.current_snapshot)

            elif sec_type == "prune":
                self._end_active_prune()

                if self.in_backup:
                    bl = self._backup_labels()
                    if bl:
                        backup_running.labels(*bl).set(0)
                        backup_speed_bps.labels(*bl).set(0)
                    self.in_backup = False

                self.in_prune = True
                self.current_storage_target = ""

                logger.info("Prune section: %s", direction)
            return

        # --- Storage URL (resolves storage_target, enables metric creation) ---
        m = RE_STORAGE_SET.search(line)
        if m:
            raw_url = m.group("storage_url")
            self.current_storage_target = _extract_storage_target(raw_url)

            if self.in_backup:
                bl = self._backup_labels()
                if bl:
                    backup_running.labels(*bl).set(1)
                    backup_progress.labels(*bl).set(0)
                    backup_speed_bps.labels(*bl).set(0)
                    backup_chunks_uploaded.labels(*bl).set(0)
                    backup_chunks_skipped.labels(*bl).set(0)
            elif self.in_prune:
                pl = self._prune_labels()
                if pl:
                    prune_running.labels(*pl).set(1)

            logger.debug("Storage target: %s (from %s)",
                         self.current_storage_target, raw_url)
            return

        # --- Chunk upload/skip (real-time progress) ---
        m = RE_CHUNK_LINE.search(line)
        if m and self.in_backup:
            bl = self._backup_labels()
            if not bl:
                return

            if m.group("action") == "Uploaded":
                self.uploaded_count += 1
                backup_chunks_uploaded.labels(*bl).set(self.uploaded_count)
            else:
                self.skipped_count += 1
                backup_chunks_skipped.labels(*bl).set(self.skipped_count)

            backup_speed_bps.labels(*bl).set(
                _parse_speed(m.group("speed"), m.group("speed_unit"))
            )
            backup_progress.labels(*bl).set(
                float(m.group("progress")) / 100.0
            )
            return

        # --- Backup completed ---
        m = RE_BACKUP_END.search(line)
        if m:
            bl = self._backup_labels()
            if not bl:
                return
            revision = int(m.group("revision"))
            backup_running.labels(*bl).set(0)
            backup_progress.labels(*bl).set(1.0)
            backup_speed_bps.labels(*bl).set(0)
            last_success_ts.labels(*bl).set(time.time())
            last_exit_code.labels(*bl).set(0)
            last_revision.labels(*bl).set(revision)
            self.in_backup = False
            logger.info("Backup completed: %s -> %s rev %d", bl[0], bl[1], revision)
            return

        # --- BACKUP_STATS Files ---
        m = RE_STATS_FILES.search(line)
        if m:
            bl = self._backup_labels()
            if not bl:
                return
            last_files_total.labels(*bl).set(int(m.group("total").replace(",", "")))
            last_files_new.labels(*bl).set(int(m.group("new").replace(",", "")))
            last_bytes_new.labels(*bl).set(
                _parse_size(m.group("new_bytes"), m.group("new_unit"))
            )
            return

        # --- BACKUP_STATS All chunks ---
        m = RE_STATS_CHUNKS.search(line)
        if m:
            bl = self._backup_labels()
            if not bl:
                return
            uploaded = _parse_size(m.group("uploaded_bytes"), m.group("uploaded_unit"))
            last_bytes_uploaded.labels(*bl).set(uploaded)
            last_chunks_new.labels(*bl).set(int(m.group("new").replace(",", "")))
            total_bytes_uploaded.labels(*bl).inc(uploaded)
            return

        # --- BACKUP_STATS Total running time ---
        m = RE_STATS_TIME.search(line)
        if m:
            bl = self._backup_labels()
            if not bl:
                return
            last_duration.labels(*bl).set(
                _parse_duration(m.group("days"), m.group("hours"),
                                m.group("minutes"), m.group("seconds"))
            )
            return

        # --- Backup failure ---
        if self.in_backup and ("Backup failed" in line or "backup failed" in line):
            bl = self._backup_labels()
            if bl:
                backup_running.labels(*bl).set(0)
                backup_speed_bps.labels(*bl).set(0)
                last_exit_code.labels(*bl).set(1)
            self.in_backup = False
            logger.warning("Backup failure detected")
            return

        # --- Prune completion ---
        if self.in_prune:
            lower = line.lower()
            if any(p in lower for p in _PRUNE_COMPLETION_PATTERNS):
                pl = self._prune_labels()
                if pl:
                    prune_running.labels(*pl).set(0)
                    last_prune_success_ts.labels(*pl).set(time.time())
                self.in_prune = False
                logger.info("Prune completed: %s", pl)
                return

        # --- Notification line (machine/snapshot, informational fallback) ---
        if "\u2014" in line and "*" in line:
            self._end_active_prune()

            machine_match = re.search(r"\*(.+?)\*", line)
            snapshot_match = re.search(r"_(.+?)_", line.split("\u2014", 1)[-1])
            if machine_match and not MACHINE_NAME:
                self.machine = machine_match.group(1)
            if snapshot_match:
                self.current_snapshot = snapshot_match.group(1)
            logger.debug("Notification: machine=%s snapshot=%s",
                         self.machine, self.current_snapshot)


# ---------------------------------------------------------------------------
# Webhook handler (for Duplicacy Web UI report_url)
# ---------------------------------------------------------------------------

class WebhookHandler:
    def __init__(self, state: BackupState):
        self.state = state

    def handle(self, payload: dict):
        snapshot_id = payload.get("id", payload.get("computer", "unknown"))
        storage = payload.get("storage", payload.get("storage_url", ""))
        storage_target = _extract_storage_target(storage) if storage else "unknown"
        machine = payload.get("computer", MACHINE_NAME or "unknown")
        labels = (snapshot_id, storage_target, machine)

        result = payload.get("result", "")
        exit_code = 0 if result.lower() == "success" else 1
        last_exit_code.labels(*labels).set(exit_code)

        if exit_code == 0:
            last_success_ts.labels(*labels).set(time.time())

        start_time = payload.get("start_time", 0)
        end_time = payload.get("end_time", 0)
        if start_time and end_time:
            last_duration.labels(*labels).set(end_time - start_time)

        last_files_total.labels(*labels).set(payload.get("total_files", 0))
        last_files_new.labels(*labels).set(payload.get("new_files", 0))
        last_chunks_new.labels(*labels).set(payload.get("new_chunks", 0))

        uploaded = payload.get("uploaded_chunk_size", 0)
        last_bytes_uploaded.labels(*labels).set(uploaded)
        last_bytes_new.labels(*labels).set(payload.get("new_file_size", 0))
        if uploaded > 0:
            total_bytes_uploaded.labels(*labels).inc(uploaded)

        duration = end_time - start_time if (start_time and end_time) else 0
        if duration > 0 and uploaded > 0:
            backup_speed_bps.labels(*labels).set(uploaded / duration)

        backup_running.labels(*labels).set(0)
        backup_progress.labels(*labels).set(1.0)

        logger.info("Webhook: %s result=%s uploaded=%d duration=%ds",
                     snapshot_id, result, uploaded, duration)


# ---------------------------------------------------------------------------
# HTTP server (serves /metrics and optionally /webhook)
# ---------------------------------------------------------------------------

class MetricsHTTPHandler(BaseHTTPRequestHandler):
    webhook_handler = None

    def do_GET(self):
        if self.path == "/metrics":
            output = generate_latest(registry)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(output)
        elif self.path in ("/health", "/healthz"):
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
        pass


# ---------------------------------------------------------------------------
# Log tail mode: Docker container logs
# ---------------------------------------------------------------------------

def tail_docker_logs(state: BackupState, container_name: str):
    """Tail Docker container logs via the Docker Engine API over Unix socket."""
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
    logger.info("Tailing log file: %s", file_path)
    while True:
        try:
            with open(file_path, "r") as f:
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
    logger.info("Starting duplicacy-exporter v%s (mode=%s, port=%d)",
                VERSION, MODE, LISTEN_PORT)

    state = BackupState()

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

    webhook = WebhookHandler(state)
    MetricsHTTPHandler.webhook_handler = webhook

    server = HTTPServer(("0.0.0.0", LISTEN_PORT), MetricsHTTPHandler)
    logger.info("Serving metrics on http://0.0.0.0:%d/metrics", LISTEN_PORT)
    logger.info("Webhook endpoint: http://0.0.0.0:%d%s", LISTEN_PORT, WEBHOOK_PATH)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
