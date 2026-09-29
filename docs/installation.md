# Installation

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
