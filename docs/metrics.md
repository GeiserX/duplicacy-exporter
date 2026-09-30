# Metrics

All backup metrics carry labels: `snapshot_id`, `storage_target`, `machine`.
All prune metrics carry labels: `storage_target`, `machine`.

Each distinct `(snapshot_id, storage_target)` is its own series (and its own device
in [duplicacy-ha](https://github.com/GeiserX/duplicacy-ha)), so multiple backups are
tracked independently. In `webhook` mode `snapshot_id` is the last path component of the
report's `directory` — so two backups on one
machine never collapse into one. In `log_tail` mode it comes from a
`DUPLICACY_META snapshot_id=…` line, a `--- Backup -> … (id) ---` section header, or
the `SNAPSHOT_ID` env var.

## Real-time (updated per chunk during backup)

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_backup_running` | Gauge | 1 if backup is in progress, 0 otherwise |
| `duplicacy_backup_speed_bytes_per_second` | Gauge | Current backup speed |
| `duplicacy_backup_progress_ratio` | Gauge | Progress from 0.0 to 1.0 |
| `duplicacy_backup_chunks_uploaded` | Gauge | Chunks uploaded in current run |
| `duplicacy_backup_chunks_skipped` | Gauge | Chunks skipped in current run |

## Post-run summary

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

## Prune

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_prune_running` | Gauge | 1 if prune is in progress |
| `duplicacy_prune_last_success_timestamp_seconds` | Gauge | Unix timestamp of last successful prune |

## Diagnostics

| Metric | Type | Description |
|--------|------|-------------|
| `duplicacy_exporter_last_activity_timestamp_seconds` | Gauge | Unix timestamp of the last log line parsed (alert if it goes stale) |
| `duplicacy_exporter_backups_seen_total` | Counter | Completed backups detected, including any dropped for a missing `snapshot_id`/`storage_target`/`machine`. If this climbs while labelled series stay empty, the exporter is seeing backups it can't label — set `SNAPSHOT_ID`/`MACHINE_NAME`. |

## Storage poller (optional, opt-in)

Only populated when the [storage poller](storage-poller.md) is enabled.
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

The HTTP endpoints (`/metrics`, `/webhook`, `/health`) are on [Usage](usage.md#endpoints).
