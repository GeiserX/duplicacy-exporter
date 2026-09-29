# Webhook payload

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
