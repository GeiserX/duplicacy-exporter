# duplicacy-exporter

<p align="center"><img src="images/banner.svg" alt="duplicacy-exporter" width="100%"></p>

A Prometheus exporter for [Duplicacy](https://duplicacy.com) backup metrics: real-time progress, speed, and
post-run summaries for your Grafana dashboards. It works with the Duplicacy CLI by tailing logs and with the
Duplicacy Web UI by webhook, and it runs as a Docker container or a PyPI package.

- [Getting started](getting-started.md): Docker Compose for log tail, webhook and log file modes, PyPI, first check.
- [Configuration](configuration.md): environment variables, storage host mapping, persistence.
- [Usage](usage.md): endpoints, reading a running and a finished backup.
    - [Metrics](metrics.md): every series and its labels.
    - [Webhook payload](webhook.md): the Web UI report fields.
    - [Storage poller](storage-poller.md): storage size and revision counts.
    - [Prometheus and Grafana](prometheus-grafana.md): scrape config, alert rules, dashboard.
- [How it works](how-it-works.md): how the two modes collect data.
- [Troubleshooting](troubleshooting.md): symptoms, causes and fixes.
- [Related projects](related.md): the rest of the Duplicacy family.

The source, the issues and the releases are on [GitHub](https://github.com/GeiserX/duplicacy-exporter). The
exporter is licensed [GPL-3.0-or-later](https://github.com/GeiserX/duplicacy-exporter/blob/main/LICENSE).
