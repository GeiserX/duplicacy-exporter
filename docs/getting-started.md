# Getting started

The exporter runs as a Docker container, `drumsergio/duplicacy-exporter` for amd64 and arm64, or as a
Python package from PyPI. Pick the mode that matches how you run Duplicacy: `log_tail` for the CLI, `webhook` for
the Web UI. Every setting is on [Configuration](configuration.md).

## Docker Compose -- Log Tail Mode (recommended for CLI)

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

## Docker Compose -- Webhook Mode (for Web UI)

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

## Docker Compose -- Log File Mode

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

## Without Docker (PyPI)

```bash
pipx install duplicacy-exporter
MODE=webhook STATE_FILE=$HOME/.duplicacy-exporter/state.json duplicacy-exporter
```

The console script reads the same environment variables as the image. The default state path is
`/data/...`, which is not writable outside the container, so point `STATE_FILE` and `TIMESTAMP_FILE`
somewhere you own, or set `PERSIST_ENABLED=false`.

## Check that it works

```bash
curl -s http://localhost:9750/health
curl -s http://localhost:9750/metrics | grep duplicacy_exporter_info
```

`/health` answers `OK`, and `/metrics` shows `duplicacy_exporter_info{mode="webhook",version="0.6.0"} 1.0`
with your mode in the label. Backup series appear after the first backup reports; [Usage](usage.md) shows what to
look at while a backup runs and after it ends.
