# Usage

Once the exporter runs and Prometheus scrapes it, there are three things to read: a backup in progress,
the summary of the last finished backup, and the exporter's own health. The full list of series is on
[Metrics](metrics.md).

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/metrics` | GET | Prometheus metrics endpoint |
| `/webhook` | POST | Duplicacy Web UI report endpoint; `WEBHOOK_PATH` changes the path |
| `/health` | GET | Health check (returns `200 OK`) |

## A backup in progress

In `log_tail` mode the exporter parses each chunk line as Duplicacy prints it, so these move while the
backup runs:

- `duplicacy_backup_running` is `1`.
- `duplicacy_backup_progress_ratio` goes from `0.0` to `1.0`.
- `duplicacy_backup_speed_bytes_per_second` shows the current upload speed.
- `duplicacy_backup_chunks_uploaded` and `duplicacy_backup_chunks_skipped` count this run's chunks.

The Web UI webhook is sent only when a backup ends, so in `webhook` mode there are no live values.

## A finished backup

When a backup ends, the `duplicacy_backup_last_*` series hold its summary: exit code, duration, file
counts, bytes uploaded, and `duplicacy_backup_last_success_timestamp_seconds`. The revision number,
`duplicacy_backup_last_revision`, comes only from `log_tail` mode, because the Web UI report does not
carry it; webhook users get revision counts from the [storage poller](storage-poller.md). These are the
values the exporter saves to `STATE_FILE`, so they survive a restart. A useful check in Prometheus:

```promql
time() - duplicacy_backup_last_success_timestamp_seconds
```

It gives the age of the last good backup, in seconds, per `snapshot_id` and `storage_target`.

Prune runs show up as `duplicacy_prune_running` and `duplicacy_prune_last_success_timestamp_seconds`,
in `log_tail` mode only. Storage size and revision counts need the [storage poller](storage-poller.md).

## Dashboards and alerts

The [Grafana dashboard #25089](https://grafana.com/grafana/dashboards/25089), the scrape
config and two alert rules are on [Prometheus and Grafana](prometheus-grafana.md). The
[duplicacy-ha](https://github.com/GeiserX/duplicacy-ha) integration reads the same `/metrics` into Home
Assistant sensors.
