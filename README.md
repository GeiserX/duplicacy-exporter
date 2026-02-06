# duplicacy-exporter

Prometheus exporter for [Duplicacy](https://duplicacy.com) backup metrics. Provides **real-time** speed, progress, and summary statistics for Grafana dashboards.

Supports both **Duplicacy CLI** (log tailing) and **Duplicacy Web UI** (webhook) setups.

## Features

- **Real-time metrics** during backup: speed (bytes/sec), progress (%), chunks uploaded/skipped
- **Summary metrics** after backup: duration, files, bytes uploaded, exit code, revision number
- **Prune tracking**: monitors prune operations
- **Two collection modes**:
  - `log_tail` — tails Docker container logs or a log file
  - `webhook` — receives JSON POST from Duplicacy Web UI's `report_url`
- Lightweight Python container (~30MB)

## Metrics

### Real-time (updated per chunk)

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
| `duplicacy_backup_last_success_timestamp_seconds` | Gauge | Unix timestamp of last success |
| `duplicacy_backup_last_duration_seconds` | Gauge | Duration of last backup |
| `duplicacy_backup_last_files_total` | Gauge | Total files in last backup |
| `duplicacy_backup_last_files_new` | Gauge | New files in last backup |
| `duplicacy_backup_last_bytes_uploaded` | Gauge | Bytes uploaded in last backup |
| `duplicacy_backup_last_bytes_new` | Gauge | New bytes in last backup |
| `duplicacy_backup_last_chunks_new` | Gauge | New chunks in last backup |
| `duplicacy_backup_last_exit_code` | Gauge | 0 = success, 1 = failure |
| `duplicacy_backup_last_revision` | Gauge | Revision number of last backup |
| `duplicacy_backup_bytes_uploaded_total` | Counter | Cumulative bytes uploaded |

### Prune

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_prune_running` | Gauge | 1 if prune is in progress |
| `duplicacy_prune_last_success_timestamp_seconds` | Gauge | Unix timestamp of last prune |

All metrics carry labels: `snapshot_id`, `storage_name`, `machine`.

## Quick Start

### Docker Compose (recommended)

Deploy alongside your Duplicacy CLI container:

```yaml
services:
  duplicacy-exporter:
    image: ghcr.io/geiserx/duplicacy-exporter:0.1.0
    container_name: duplicacy-exporter
    restart: unless-stopped
    environment:
      - MODE=log_tail
      - DOCKER_CONTAINER_NAME=duplicacy-cli-cron
      - LISTEN_PORT=9750
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "9750:9750"
```

### Webhook Mode (for Duplicacy Web UI)

```yaml
services:
  duplicacy-exporter:
    image: ghcr.io/geiserx/duplicacy-exporter:0.1.0
    container_name: duplicacy-exporter
    restart: unless-stopped
    environment:
      - MODE=webhook
      - LISTEN_PORT=9750
    ports:
      - "9750:9750"
```

Then set `report_url` in Duplicacy Web UI to: `http://duplicacy-exporter:9750/webhook`

### Log File Mode

If you write Duplicacy logs to a file instead of Docker:

```yaml
services:
  duplicacy-exporter:
    image: ghcr.io/geiserx/duplicacy-exporter:0.1.0
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

| Variable | Default | Description |
|----------|---------|-------------|
| `MODE` | `log_tail` | Collection mode: `log_tail` or `webhook` |
| `DOCKER_CONTAINER_NAME` | `duplicacy-cli-cron` | Container name to tail logs from |
| `LOG_FILE` | _(empty)_ | Path to log file (alternative to Docker socket) |
| `LISTEN_PORT` | `9750` | Port for metrics and webhook HTTP server |
| `WEBHOOK_PATH` | `/webhook` | Path for webhook POST endpoint |
| `MACHINE_NAME` | _(empty)_ | Machine name label (auto-detected from logs) |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |

## Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'duplicacy'
    static_configs:
      - targets: ['duplicacy-exporter:9750']
        labels:
          instance: 'my-server'
```

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/metrics` | GET | Prometheus metrics |
| `/webhook` | POST | Duplicacy Web UI report endpoint |
| `/health` | GET | Health check (returns 200 OK) |

## License

[GPL-3.0](LICENSE)
