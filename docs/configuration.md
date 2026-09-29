# Configuration

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
| `POLLER_ENABLED` | `false` | Enable the optional [storage poller](storage-poller.md#storage-poller-optional). Truthy values: `1`, `true`, `yes`. Off by default. |
| `POLLER_INTERVAL` | `86400` | Seconds between storage poller cycles (default 24h) |
| `POLLER_REPOSITORIES` | _(empty)_ | JSON list of repositories to poll. Each item: `{"path": "...", "storage": "...", "snapshot_id": "..."}` (`path` required; `storage` defaults to `default`; `snapshot_id` optional) |
| `DUPLICACY_BIN` | `duplicacy` | Path to the duplicacy CLI binary used by the poller |
| `POLLER_TIMEOUT` | `1800` | Per-command timeout in seconds for `duplicacy list` / `check` |

## Storage host mapping example

Map raw IPs or hostnames to friendly names:

```bash
STORAGE_HOST_MAP='{"192.168.10.100":"watchtower","192.168.20.5":"geiserct"}'
```

## Persistence across restarts

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
