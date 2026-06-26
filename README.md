<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/duplicacy-exporter/main/docs/images/banner.svg" alt="duplicacy-exporter banner" width="900"/>
</p>

<p align="center">
  <strong>Prometheus exporter for <a href="https://duplicacy.com">Duplicacy</a> backup metrics -- real-time progress, speed, and post-run summaries for your Grafana dashboards.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/duplicacy-exporter/"><img src="https://img.shields.io/pypi/v/duplicacy-exporter?style=flat-square&logo=python&logoColor=white&label=PyPI" alt="PyPI"></a>
  <a href="https://github.com/GeiserX/duplicacy-exporter/releases"><img src="https://img.shields.io/github/v/release/GeiserX/duplicacy-exporter?style=flat-square&color=E6522C" alt="GitHub Release"></a>
  <a href="https://hub.docker.com/r/drumsergio/duplicacy-exporter"><img src="https://img.shields.io/docker/v/drumsergio/duplicacy-exporter?sort=semver&style=flat-square&logo=docker&label=Docker%20Hub" alt="Docker Hub"></a>
  <a href="https://grafana.com/grafana/dashboards/25089"><img src="https://img.shields.io/badge/Grafana-Dashboard%2025089-F46800?style=flat-square&logo=grafana&logoColor=white" alt="Grafana Dashboard"></a>
  <a href="https://github.com/GeiserX/duplicacy-exporter/blob/main/LICENSE"><img src="https://img.shields.io/github/license/GeiserX/duplicacy-exporter?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.13-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/image%20size-~30MB-green?style=flat-square" alt="Image Size">
  <a href="https://codecov.io/gh/GeiserX/duplicacy-exporter"><img src="https://img.shields.io/codecov/c/github/GeiserX/duplicacy-exporter?style=flat-square" alt="Coverage"></a>
</p>

---

## Overview

**duplicacy-exporter** bridges [Duplicacy](https://duplicacy.com) backups and [Prometheus](https://prometheus.io), giving you full observability over backup operations. It works with both **Duplicacy CLI** (via log tailing) and **Duplicacy Web UI** (via webhook), exposing metrics that Prometheus scrapes and Grafana visualizes.

### Key capabilities

- **Real-time metrics** -- backup speed (bytes/sec), progress (0-100%), chunks uploaded/skipped, updated per chunk
- **Post-run summaries** -- duration, file counts, bytes uploaded, exit codes, revision numbers
- **Prune tracking** -- monitors prune operations with completion timestamps
- **Two collection modes** -- `log_tail` for CLI users, `webhook` for Web UI users
- **Smart label resolution** -- automatic snapshot ID, storage target, and machine name detection from logs
- **Storage host mapping** -- translates IPs and Tailscale FQDNs into human-readable names
- **Lightweight** -- single Python file, one dependency (`prometheus_client`), Alpine image (~30 MB)

## Architecture

```
+---------------------+         +----------------------+         +------------+
|                     |  logs   |                      | scrape  |            |
|  Duplicacy CLI      +-------->+  duplicacy-exporter  +<--------+ Prometheus |
|  (Docker / file)    |  tail   |                      |  :9750  |            |
+---------------------+         +----------+-----------+         +------+-----+
                                           |                            |
+---------------------+  POST   |          |                            |
|  Duplicacy Web UI   +-------->+  /webhook endpoint   |         +------v-----+
|  (report_url)       |         |                      |         |  Grafana   |
+---------------------+         +----------------------+         +------------+
```

**Log tail mode** connects to the Docker Engine API over a Unix socket (or tails a log file) and parses Duplicacy output line-by-line. It extracts chunk-level progress in real time and summary statistics at completion.

**Webhook mode** receives JSON payloads from Duplicacy Web UI's `report_url` setting, extracting the same summary metrics without needing Docker socket access.

## Quick Start

### Docker Compose -- Log Tail Mode (recommended for CLI)

Deploy alongside your Duplicacy CLI container using a shared log volume:

```yaml
services:
  duplicacy-exporter:
    image: drumsergio/duplicacy-exporter:0.6.0
    container_name: duplicacy-exporter
    restart: unless-stopped
    environment:
      - MODE=log_tail
      - LOG_FILE=/logs/duplicacy.log
      - LISTEN_PORT=9750
    volumes:
      - duplicacy-logs:/logs:ro
    ports:
      - "9750:9750"

volumes:
  duplicacy-logs:
```

> **Note:** Mount the same `duplicacy-logs` volume in your Duplicacy container, writing output to `/logs/duplicacy.log`. This avoids exposing the Docker socket.

### Docker Compose -- Webhook Mode (for Web UI)

```yaml
services:
  duplicacy-exporter:
    image: drumsergio/duplicacy-exporter:0.6.0
    container_name: duplicacy-exporter
    restart: unless-stopped
    environment:
      - MODE=webhook
      - LISTEN_PORT=9750
    ports:
      - "9750:9750"
```

Then set `report_url` in Duplicacy Web UI to: `http://duplicacy-exporter:9750/webhook`

### Docker Compose -- Log File Mode

If you write Duplicacy logs to a file instead of using Docker:

```yaml
services:
  duplicacy-exporter:
    image: drumsergio/duplicacy-exporter:0.6.0
    container_name: duplicacy-exporter
    restart: unless-stopped
    environment:
      - MODE=log_tail
      - LOG_FILE=/logs/duplicacy.log
      - LISTEN_PORT=9750
    volumes:
      - /path/to/duplicacy/logs:/logs:ro
    ports:
      - "9750:9750"
```

## Configuration

All configuration is done through environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODE` | `log_tail` | Collection mode: `log_tail` or `webhook` |
| `DOCKER_CONTAINER_NAME` | `duplicacy-cli-cron` | Container name to tail logs from (log_tail mode) |
| `LOG_FILE` | _(empty)_ | Path to log file; alternative to Docker socket (log_tail mode) |
| `LISTEN_PORT` | `9750` | Port for the metrics and webhook HTTP server |
| `WEBHOOK_PATH` | `/webhook` | Path for the webhook POST endpoint (webhook mode) |
| `MACHINE_NAME` | _(empty)_ | Machine name label. In `log_tail` mode it must be set (or learned from a `DUPLICACY_META` / notification line) before backup metrics are emitted. |
| `SNAPSHOT_ID` | _(empty)_ | Snapshot id for `log_tail` users whose logs have no section headers / `DUPLICACY_META` (e.g. stock `duplicacy backup`). Lets post-run summary metrics resolve. |
| `TAILSCALE_DOMAIN` | `mango-alpha.ts.net` | Tailscale domain suffix to strip from storage URLs |
| `STORAGE_HOST_MAP` | _(empty)_ | JSON object mapping hostname/IP to display name |
| `REPLAY_HOURS` | `25` | Hours of Docker log history to replay on startup |
| `TIMESTAMP_FILE` | `/data/duplicacy_exporter_last_ts` | File to persist last-seen log timestamp (avoids counter double-count on restart). Co-located with `STATE_FILE` under `/data` so one volume persists both. |
| `MAX_LOG_BUFFER` | `1048576` | Maximum Docker log buffer size in bytes before discarding partial data (1 MB) |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PERSIST_ENABLED` | `true` | Save the last completed backup/storage/prune values to disk and reload them on startup, so metrics survive a restart (see [Persistence](#persistence-across-restarts)). Set to `false` to opt out. |
| `STATE_FILE` | `/data/duplicacy_exporter_state.json` | Where the durable metric state is stored. Mount a volume at its directory so state survives container re-creation, not just restarts. |
| `PERSIST_INTERVAL` | `15` | Seconds between state snapshots. A snapshot is only written when a value actually changed. |
| `POLLER_ENABLED` | `false` | Enable the optional [storage poller](#storage-poller-optional). Truthy values: `1`, `true`, `yes`. Off by default. |
| `POLLER_INTERVAL` | `86400` | Seconds between storage poller cycles (default 24h) |
| `POLLER_REPOSITORIES` | _(empty)_ | JSON list of repositories to poll. Each item: `{"path": "...", "storage": "...", "snapshot_id": "..."}` (`path` required; `storage` defaults to `default`; `snapshot_id` optional) |
| `DUPLICACY_BIN` | `duplicacy` | Path to the duplicacy CLI binary used by the poller |
| `POLLER_TIMEOUT` | `1800` | Per-command timeout in seconds for `duplicacy list` / `check` |

### Storage host mapping example

Map raw IPs or hostnames to friendly names:

```bash
STORAGE_HOST_MAP='{"192.168.10.100":"watchtower","192.168.20.5":"geiserct"}'
```

### Persistence across restarts

Prometheus metrics live only in memory, so without persistence a restart wipes
them: in `webhook` mode the values stay gone until the *next* backup reports,
which can leave Home Assistant sensors `unavailable`/`unknown` for hours.

Persistence is **on by default**. The last completed backup, storage-poller and
prune values are snapshotted to `STATE_FILE` (default `/data/duplicacy_exporter_state.json`)
and reloaded on startup, so `/metrics` re-serves them immediately. Only durable
"last completed" values are persisted — the real-time progress gauges
(`*_running`, `*_speed_*`, `*_progress_*`, live chunk counts) are not, since they
reflect an in-flight backup and settle from live data within one cycle.

Mount a volume at the state file's directory so it also survives container
**re-creation** (image upgrades), not just a `docker restart`:

```yaml
    volumes:
      - duplicacy-exporter-data:/data   # or a bind mount, e.g. /mnt/user/appdata/duplicacy-exporter:/data
```

If the directory is not writable the exporter logs one warning and continues
without persistence (metrics still work, they just won't survive a restart).

## Metrics

All backup metrics carry labels: `snapshot_id`, `storage_target`, `machine`.
All prune metrics carry labels: `storage_target`, `machine`.

Each distinct `(snapshot_id, storage_target)` is its own series (and its own device
in [duplicacy-ha](https://github.com/GeiserX/duplicacy-ha)), so multiple backups are
tracked independently. In `webhook` mode `snapshot_id` comes from the Web UI report's
backup id, falling back to the source **directory** name — so two backups on one
machine never collapse into one. In `log_tail` mode it comes from a
`DUPLICACY_META snapshot_id=…` line, a `--- Backup -> … (id) ---` section header, or
the `SNAPSHOT_ID` env var.

### Real-time (updated per chunk during backup)

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_backup_running` | Gauge | 1 if backup is in progress, 0 otherwise |
| `duplicacy_backup_speed_bytes_per_second` | Gauge | Current backup speed |
| `duplicacy_backup_progress_ratio` | Gauge | Progress from 0.0 to 1.0 |
| `duplicacy_backup_chunks_uploaded` | Gauge | Chunks uploaded in current run |
| `duplicacy_backup_chunks_skipped` | Gauge | Chunks skipped in current run |

### Post-run summary

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_backup_last_success_timestamp_seconds` | Gauge | Unix timestamp of last successful backup |
| `duplicacy_backup_last_duration_seconds` | Gauge | Duration of last backup in seconds |
| `duplicacy_backup_last_files_total` | Gauge | Total files in last backup |
| `duplicacy_backup_last_files_new` | Gauge | New files in last backup |
| `duplicacy_backup_last_bytes_uploaded` | Gauge | Bytes uploaded in last backup |
| `duplicacy_backup_last_bytes_new` | Gauge | New bytes in last backup |
| `duplicacy_backup_last_chunks_new` | Gauge | New chunks in last backup |
| `duplicacy_backup_last_files_size_bytes` | Gauge | Total logical size of all files in the last backup snapshot (webhook: `total_file_size`) |
| `duplicacy_backup_last_chunks_size_bytes` | Gauge | Total size of chunks referenced by the last backup, compressed and **not** deduplicated across revisions (webhook: `total_chunk_size`) |
| `duplicacy_backup_last_exit_code` | Gauge | Exit code: 0 = success, 1 = failure |
| `duplicacy_backup_last_revision` | Gauge | Revision number of last backup |
| `duplicacy_backup_bytes_uploaded_total` | Counter | Cumulative bytes uploaded across all runs |

### Prune

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_prune_running` | Gauge | 1 if prune is in progress |
| `duplicacy_prune_last_success_timestamp_seconds` | Gauge | Unix timestamp of last successful prune |

### Diagnostics

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_exporter_last_activity_timestamp_seconds` | Gauge | Unix timestamp of the last log line parsed (alert if it goes stale) |
| `duplicacy_exporter_backups_seen_total` | Counter | Completed backups detected, including any dropped for a missing `snapshot_id`/`storage_target`/`machine`. If this climbs while labelled series stay empty, the exporter is seeing backups it can't label — set `SNAPSHOT_ID`/`MACHINE_NAME`. |

### Storage poller (optional, opt-in)

Only populated when the [storage poller](#storage-poller-optional) is enabled.
Storage metrics carry labels `storage_target`, `machine`; snapshot metrics carry
`snapshot_id`, `storage_target`, `machine`.

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_storage_total_size_bytes` | Gauge | Total size of all chunks in the storage, from `duplicacy check`. Approximate — reconstructed from Duplicacy's human-readable size formatting (worst case ~0.65% low). |
| `duplicacy_storage_total_chunks` | Gauge | Total number of chunks in the storage, from `duplicacy check` |
| `duplicacy_snapshot_revisions` | Gauge | Number of revisions for a snapshot id, from `duplicacy list` |
| `duplicacy_snapshot_last_revision` | Gauge | Highest (latest) revision number for a snapshot id, from `duplicacy list` |
| `duplicacy_poller_last_success_timestamp_seconds` | Gauge | Unix timestamp of the last fully successful poller cycle |
| `duplicacy_poller_errors_total` | Counter | Poller errors (missing binary, timeout, or parse failure) across all cycles |

## Webhook payload

In `webhook` mode the exporter consumes Duplicacy **Web UI's** `report_url` POST.
That report is a single flat JSON object and is sent **only for backups** (not for
prune, copy, or check). It carries these 26 fields:

| Field | Meaning |
|-------|---------|
| `computer` | Machine name (used for the `machine` label) |
| `directory` | Source directory backed up (the per-backup differentiator → `snapshot_id`) |
| `start_time`, `end_time` | Unix timestamps; their difference is the duration |
| `result` | `"Success"` or `"Error"` (capitalized) |
| `storage`, `storage_url` | Destination storage URL (used for the `storage_target` label) |
| `total_files`, `new_files` | File counts (total / new this revision) |
| `total_file_size`, `new_file_size` | Logical file bytes (total / new) |
| `total_chunks`, `new_chunks` | Chunk counts (total / new) |
| `total_chunk_size`, `new_chunk_size` | Chunk bytes after compression (total / new) |
| `total_file_chunks`, `new_file_chunks` | File-content chunk counts |
| `total_file_chunk_size`, `new_file_chunk_size` | File-content chunk bytes |
| `total_metadata_chunks`, `new_metadata_chunks` | Metadata chunk counts |
| `total_metadata_chunk_size`, `new_metadata_chunk_size` | Metadata chunk bytes |
| `upload_chunk_size` | **Bytes actually uploaded** this run (note: no "d" — `upload`, not `uploaded`) |
| `upload_file_chunk_size`, `upload_metadata_chunk_size` | Uploaded file / metadata chunk bytes |

> **There is no `id`, `snapshot_id`, `revision`, `prune`, or storage-size field in
> this payload.** The exporter differentiates backups by `directory`, and uses the
> poller (below) for storage size and revision counts.

## Storage poller (optional)

The Web UI webhook **cannot** carry storage size or revision counts. The optional
storage poller fills that gap by periodically running the duplicacy CLI:

- `duplicacy -log list -all` → revision count and latest revision per snapshot id
- `duplicacy -log check -tabular -stats` → total chunk count and total storage size

Enable it with `POLLER_ENABLED=true` and a `POLLER_REPOSITORIES` JSON list:

```yaml
environment:
  - POLLER_ENABLED=true
  - POLLER_INTERVAL=86400          # once a day
  - POLLER_REPOSITORIES=[{"path":"/repos/photos","storage":"watchtower","snapshot_id":"photos"}]
volumes:
  - /srv/duplicacy/photos:/repos/photos   # an initialised duplicacy repository
```

> **⚠️ Security & cost.** The poller **runs the `duplicacy` binary against your
> storage**, so it needs the binary (bundled in the image) **plus storage
> credentials and an initialised repository inside the exporter container**
> (mount the repo's `.duplicacy` directory or provide credentials via the
> environment). It is **opt-in and off by default** for this reason. `check` can
> be **slow and costly** on remote storage (it lists every chunk), so keep
> `POLLER_INTERVAL` large. The exporter still runs fine without the poller — the
> bundled binary simply enables it.

### What lives where

| You want… | Use |
|-----------|-----|
| Per-run speed, progress, files, uploaded bytes | `log_tail` **or** `webhook` |
| **Storage size** + **revision counts** | **poller** (not in the webhook) |
| **Prune** completion tracking | `log_tail` (not in the webhook, not in the poller) |

The storage-size value is **approximate**: Duplicacy's `check` prints sizes in a
lossy human format (e.g. `5,120M`), which the exporter converts back to bytes.

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/metrics` | GET | Prometheus metrics endpoint |
| `/webhook` | POST | Duplicacy Web UI report endpoint |
| `/health` | GET | Health check (returns `200 OK`) |

## Prometheus Configuration

Add the exporter as a scrape target:

```yaml
scrape_configs:
  - job_name: "duplicacy"
    static_configs:
      - targets: ["duplicacy-exporter:9750"]
        labels:
          instance: "my-server"
```

### Example alerting rule

```yaml
groups:
  - name: duplicacy
    rules:
      - alert: DuplicacyBackupFailed
        expr: duplicacy_backup_last_exit_code != 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Duplicacy backup failed for {{ $labels.snapshot_id }}"

      - alert: DuplicacyBackupStale
        expr: time() - duplicacy_backup_last_success_timestamp_seconds > 86400
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "No successful Duplicacy backup in 24h for {{ $labels.snapshot_id }}"
```

## Grafana Dashboard

A ready-to-import dashboard is included in [`dashboard.json`](dashboard.json) and published on [Grafana.com (#25089)](https://grafana.com/grafana/dashboards/25089).

Import it in Grafana via **Dashboards → Import → Upload JSON file** or use the dashboard ID `25089`.

## Troubleshooting

### Exporter starts but no metrics appear

- **Log tail mode**: Verify the Docker socket is mounted (`/var/run/docker.sock:/var/run/docker.sock:ro`) and the `DOCKER_CONTAINER_NAME` matches your Duplicacy container exactly.
- **Log file mode**: Confirm the log file path is correct and the volume mount provides read access.
- **Webhook mode**: Ensure `report_url` in Duplicacy Web UI points to `http://<exporter-host>:9750/webhook`. The exporter must be reachable from the Web UI container.

### Metrics show but labels are wrong or missing

- Set `LOG_LEVEL=DEBUG` to see how each log line is parsed and which labels are resolved.
- If storage targets show as raw IPs, use `STORAGE_HOST_MAP` to map them to friendly names.
- If machine name is missing, set `MACHINE_NAME` explicitly.

### Metrics (or HA sensors) disappear after restarting the exporter

- Persistence is on by default — confirm `STATE_FILE`'s directory is a **writable mounted volume** (default `/data`). Without a volume the state is lost when the container is re-created on an image upgrade.
- Check the logs for `Disabling metric persistence; cannot write …`: the directory isn't writable. Mount a volume or set `STATE_FILE` to a writable path.
- See [Persistence across restarts](#persistence-across-restarts) for details.

### Docker socket permission denied

The exporter process runs as root inside the container by default. If you run it as a non-root user, ensure the user has access to the Docker socket (typically group `docker`, GID 999 or similar).

### Webhook returns 404

Verify the `WEBHOOK_PATH` environment variable matches the path you configured in Duplicacy Web UI. The default is `/webhook`.

## Related Projects

- [`duplicacy-container`](https://github.com/GeiserX/duplicacy-container) -- Runtime image and Helm chart for the Kubernetes Duplicacy stack
- [`duplicacy-cli-cron`](https://github.com/GeiserX/duplicacy-cli-cron) -- Scripts, wrappers, and backup recipes for Duplicacy CLI
- [`duplicacy-ha`](https://github.com/GeiserX/duplicacy-ha) -- Home Assistant integration for Duplicacy
- [`duplicacy-mcp`](https://github.com/GeiserX/duplicacy-mcp) -- MCP server for Duplicacy
- [Duplicacy](https://duplicacy.com) -- Lock-free deduplication cloud backup tool
- [Prometheus](https://prometheus.io) -- Monitoring and alerting toolkit
- [Grafana](https://grafana.com) -- Observability and visualization platform
- [awesome-prometheus](https://github.com/roaldnefs/awesome-prometheus) -- Curated list of Prometheus resources
- [prometheus_client (Python)](https://github.com/prometheus/client_python) -- Official Prometheus client library for Python

## License

[GPL-3.0](LICENSE)
