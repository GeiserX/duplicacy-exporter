# How it works

<p>
  <a href="https://grafana.com/grafana/dashboards/25089"><img src="https://img.shields.io/badge/Grafana-Dashboard%2025089-F46800?style=flat-square&logo=grafana&logoColor=white" alt="Grafana Dashboard"></a>
  <img src="https://img.shields.io/badge/python-3.13-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/image%20size-~30MB-green?style=flat-square" alt="Image Size">
</p>

**duplicacy-exporter** bridges [Duplicacy](https://duplicacy.com) backups and [Prometheus](https://prometheus.io), giving you full observability over backup operations. It works with both **Duplicacy CLI** (via log tailing) and **Duplicacy Web UI** (via webhook), exposing metrics that Prometheus scrapes and Grafana visualizes.

## Key capabilities

- **Real-time metrics** -- backup speed (bytes/sec), progress (0-100%), chunks uploaded/skipped, updated per chunk
- **Post-run summaries** -- duration, file counts, bytes uploaded, exit codes, revision numbers
- **Prune tracking** -- monitors prune operations with completion timestamps
- **Two collection modes** -- `log_tail` for CLI users, `webhook` for Web UI users
- **Smart label resolution** -- automatic snapshot ID, storage target, and machine name detection from logs
- **Storage host mapping** -- translates IPs and Tailscale FQDNs into human-readable names
- **Lightweight** -- single Python file, one dependency (`prometheus_client`), Alpine image (~30 MB)

## Collection modes

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
