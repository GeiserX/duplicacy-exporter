<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/duplicacy-exporter/main/docs/images/banner.svg" alt="duplicacy-exporter" width="900"/>
</p>

<p align="center">
  <strong>Prometheus exporter for <a href="https://duplicacy.com">Duplicacy</a> backup metrics: real-time progress, speed, and post-run summaries for your Grafana dashboards.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/duplicacy-exporter/"><img src="https://img.shields.io/pypi/v/duplicacy-exporter?style=flat-square&logo=python&logoColor=white&label=PyPI" alt="PyPI"></a>
  <a href="https://github.com/GeiserX/duplicacy-exporter/releases"><img src="https://img.shields.io/github/v/release/GeiserX/duplicacy-exporter?style=flat-square&color=E6522C" alt="GitHub Release"></a>
  <a href="https://hub.docker.com/r/drumsergio/duplicacy-exporter"><img src="https://img.shields.io/docker/v/drumsergio/duplicacy-exporter?sort=semver&style=flat-square&logo=docker&label=Docker%20Hub" alt="Docker Hub"></a>
  <a href="https://github.com/GeiserX/duplicacy-exporter/blob/main/LICENSE"><img src="https://img.shields.io/github/license/GeiserX/duplicacy-exporter?style=flat-square" alt="License"></a>
</p>

It works with **Duplicacy CLI** (by tailing logs) and **Duplicacy Web UI** (by webhook), and exposes metrics that [Prometheus](https://prometheus.io) scrapes and Grafana shows. It runs as a Docker container or a PyPI package.

## Features

- Real-time backup speed, progress and chunks uploaded or skipped, updated per chunk.
- Post-run summaries: duration, file counts, bytes uploaded, exit code, revision number.
- Prune tracking with completion timestamps.
- Two collection modes: `log_tail` for CLI users, `webhook` for Web UI users.
- Detects snapshot ID, storage target and machine name from the logs, and maps IPs and Tailscale names to readable hosts.
- Keeps the last completed values across restarts.
- Optional storage poller for storage size and revision counts.
- A ready-made [Grafana dashboard (#25089)](https://grafana.com/grafana/dashboards/25089).
- Single Python file, one dependency (`prometheus_client`), Alpine image of about 30 MB.

## Quick start

```bash
docker run -d --name duplicacy-exporter -p 9750:9750 -e MODE=webhook drumsergio/duplicacy-exporter:0.6.0
```

Then set `report_url` in Duplicacy Web UI to `http://duplicacy-exporter:9750/webhook` and scrape `:9750/metrics`. Without Docker: `pipx install duplicacy-exporter`, then run `duplicacy-exporter`. For the CLI (`log_tail`) and log-file setups, see [Getting started](https://geiserx.github.io/duplicacy-exporter/getting-started/).

## Documentation

The full documentation lives at **[geiserx.github.io/duplicacy-exporter](https://geiserx.github.io/duplicacy-exporter/)**.

- [Getting started](https://geiserx.github.io/duplicacy-exporter/getting-started/): Docker Compose for log tail, webhook and log file modes, PyPI, first check
- [Configuration](https://geiserx.github.io/duplicacy-exporter/configuration/): environment variables, storage host mapping, persistence
- [Usage](https://geiserx.github.io/duplicacy-exporter/usage/): endpoints, reading a running and a finished backup
- [Metrics](https://geiserx.github.io/duplicacy-exporter/metrics/): every series and its labels
- [Webhook payload](https://geiserx.github.io/duplicacy-exporter/webhook/): the Web UI report fields
- [Storage poller](https://geiserx.github.io/duplicacy-exporter/storage-poller/): storage size and revision counts
- [Prometheus and Grafana](https://geiserx.github.io/duplicacy-exporter/prometheus-grafana/): scrape config, alert rules, dashboard
- [How it works](https://geiserx.github.io/duplicacy-exporter/how-it-works/): how the two modes collect data
- [Troubleshooting](https://geiserx.github.io/duplicacy-exporter/troubleshooting/)
- [Related projects](https://geiserx.github.io/duplicacy-exporter/related/)

## License

[GPL-3.0-or-later](https://github.com/GeiserX/duplicacy-exporter/blob/main/LICENSE)
