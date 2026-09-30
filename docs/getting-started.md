# Getting started

The exporter runs as a Docker container, `drumsergio/duplicacy-exporter` for amd64 and arm64, or as a Python
package from PyPI. Pick the mode that matches how you run Duplicacy: `log_tail` for the CLI, `webhook` for the
Web UI. Every setting is on [Configuration](configuration.md).

## Docker Compose

=== "CLI, shared log file"

    Your Duplicacy container writes its log to a volume; the exporter tails it. Live progress needs the
    `--- Backup -> Primary (<id>) ---` section headers that
    [duplicacy-cli-cron](https://github.com/GeiserX/duplicacy-cli-cron) writes; a plain `duplicacy backup` log
    gives the post-run summary only, and then `SNAPSHOT_ID` must be set.

    ```yaml
    services:
      duplicacy-exporter:
        image: drumsergio/duplicacy-exporter:0.6.0
        container_name: duplicacy-exporter
        restart: unless-stopped
        environment:
          - MODE=log_tail
          - LOG_FILE=/logs/duplicacy.log
          - MACHINE_NAME=homeserver
        volumes:
          - duplicacy-logs:/logs:ro
          - duplicacy-exporter-data:/data
        ports:
          - "9750:9750"

    volumes:
      duplicacy-logs:
      duplicacy-exporter-data:
    ```

    Mount the same `duplicacy-logs` volume in the Duplicacy container and write its output to
    `/logs/duplicacy.log`. This needs no Docker socket.

=== "CLI, container logs"

    The exporter reads the Duplicacy container's own log stream through the Docker socket. Same headers
    requirement as the log file.

    ```yaml
    services:
      duplicacy-exporter:
        image: drumsergio/duplicacy-exporter:0.6.0
        container_name: duplicacy-exporter
        restart: unless-stopped
        environment:
          - MODE=log_tail
          - DOCKER_CONTAINER_NAME=duplicacy-cli-cron
          - MACHINE_NAME=homeserver
        volumes:
          - /var/run/docker.sock:/var/run/docker.sock:ro
          - duplicacy-exporter-data:/data
        ports:
          - "9750:9750"

    volumes:
      duplicacy-exporter-data:
    ```

    `:ro` stops writes to the socket file, not calls to the Docker API: whoever controls the exporter can
    drive the Docker daemon, and on a rootful daemon that means the host. If that is too much, use the
    shared log file instead.

    On start it replays the last `REPLAY_HOURS` (25) of the container's log, so the last completed run shows
    at once.

=== "Web UI, webhook"

    ```yaml
    services:
      duplicacy-exporter:
        image: drumsergio/duplicacy-exporter:0.6.0
        container_name: duplicacy-exporter
        restart: unless-stopped
        environment:
          - MODE=webhook
        volumes:
          - duplicacy-exporter-data:/data
        ports:
          - "9750:9750"

    volumes:
      duplicacy-exporter-data:
    ```

    In the Web UI, set `report_url` to `http://<address of the exporter host>:9750/webhook`. Use the container
    name (`http://duplicacy-exporter:9750/webhook`) only when the Web UI container and the exporter share a
    Docker network. The report arrives when a backup ends, so this mode has no live values; see
    [Usage](usage.md).

The `/data` volume holds the last completed values so they survive a restart and an image upgrade. See
[Persistence across restarts](configuration.md#persistence-across-restarts).

Port 9750 has no authentication, and `/webhook` accepts a report in every mode, so anyone who can reach
the port can post fake backup results. Publish it only to a network you trust, for example
`"127.0.0.1:9750:9750"` when Prometheus runs on the same host.

## Without Docker (PyPI)

```bash
pipx install duplicacy-exporter
MODE=webhook STATE_FILE=$HOME/.duplicacy-exporter/state.json duplicacy-exporter
```

The console script reads the same environment variables as the image. The default state path is
`/data/...`, which is not writable outside the container, so point `STATE_FILE` and `TIMESTAMP_FILE`
somewhere you own, or set `PERSIST_ENABLED=false`. Python 3.10 or newer.

## Check that it works

```bash
curl -s http://localhost:9750/health
curl -s http://localhost:9750/metrics | grep duplicacy_exporter_info
```

`/health` answers `OK`, and `/metrics` shows `duplicacy_exporter_info{mode="webhook",version="0.6.0"} 1.0`
with your mode in the label. Backup series appear after the first backup reports. In `log_tail` mode, if
`duplicacy_exporter_backups_seen_total` climbs while no labelled series appears, the exporter saw a backup it
could not label: set `SNAPSHOT_ID` and `MACHINE_NAME`. [Usage](usage.md) shows what to look at while a backup
runs and after it ends, and [Prometheus and Grafana](prometheus-grafana.md) has the scrape job, the alert
rules and the dashboard.
