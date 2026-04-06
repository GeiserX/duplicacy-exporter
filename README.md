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

Deploy alongside your Duplicacy CLI container:

```yaml
services:
  duplicacy-exporter:
    image: drumsergio/duplicacy-exporter:0.3.4
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

### Docker Compose -- Webhook Mode (for Web UI)

```yaml
services:
  duplicacy-exporter:
    image: drumsergio/duplicacy-exporter:0.3.4
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
    image: drumsergio/duplicacy-exporter:0.3.4
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
| `MACHINE_NAME` | _(empty)_ | Machine name label; auto-detected from logs if not set |
| `TAILSCALE_DOMAIN` | `mango-alpha.ts.net` | Tailscale domain suffix to strip from storage URLs |
| `STORAGE_HOST_MAP` | _(empty)_ | JSON object mapping hostname/IP to display name |
| `REPLAY_HOURS` | `25` | Hours of Docker log history to replay on startup |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Storage host mapping example

Map raw IPs or hostnames to friendly names:

```bash
STORAGE_HOST_MAP='{"192.168.10.100":"watchtower","192.168.20.5":"geiserct"}'
```

## Metrics

All backup metrics carry labels: `snapshot_id`, `storage_target`, `machine`.
All prune metrics carry labels: `storage_target`, `machine`.

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
| `duplicacy_backup_last_exit_code` | Gauge | Exit code: 0 = success, 1 = failure |
| `duplicacy_backup_last_revision` | Gauge | Revision number of last backup |
| `duplicacy_backup_bytes_uploaded_total` | Counter | Cumulative bytes uploaded across all runs |

### Prune

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_prune_running` | Gauge | 1 if prune is in progress |
| `duplicacy_prune_last_success_timestamp_seconds` | Gauge | Unix timestamp of last successful prune |

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

### Docker socket permission denied

The exporter process runs as root inside the container by default. If you run it as a non-root user, ensure the user has access to the Docker socket (typically group `docker`, GID 999 or similar).

### Webhook returns 404

Verify the `WEBHOOK_PATH` environment variable matches the path you configured in Duplicacy Web UI. The default is `/webhook`.

## Related Projects

- [`duplicacy-container`](https://github.com/GeiserX/duplicacy-container) -- Runtime image and Helm chart for the Kubernetes Duplicacy stack
- [`duplicacy-cli-cron`](https://github.com/GeiserX/duplicacy-cli-cron) -- Scripts, wrappers, and backup recipes for Duplicacy CLI
- [Duplicacy](https://duplicacy.com) -- Lock-free deduplication cloud backup tool
- [Prometheus](https://prometheus.io) -- Monitoring and alerting toolkit
- [Grafana](https://grafana.com) -- Observability and visualization platform
- [awesome-prometheus](https://github.com/roaldnefs/awesome-prometheus) -- Curated list of Prometheus resources
- [prometheus_client (Python)](https://github.com/prometheus/client_python) -- Official Prometheus client library for Python

## License

[GPL-3.0](LICENSE)
