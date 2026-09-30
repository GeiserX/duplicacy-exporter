# Troubleshooting

## Summaries appear but the gauge never moves

Live progress needs a section header (`--- Backup -> Primary (<id>) ---`) to open a run; a plain
`duplicacy backup` log has none, so chunk lines are ignored and only the post-run summary is recorded. Use
[duplicacy-cli-cron](https://github.com/GeiserX/duplicacy-cli-cron), or wrap your job so it prints that line
before `duplicacy backup` starts. The Web UI reports only when a backup ends, so `webhook` mode never has live
values.

## Exporter starts but no metrics appear

- **Log tail mode**: Verify the Docker socket is mounted (`/var/run/docker.sock:/var/run/docker.sock:ro`) and the `DOCKER_CONTAINER_NAME` matches your Duplicacy container exactly.
- **Log file mode**: Confirm the log file path is correct and the volume mount provides read access.
- **Webhook mode**: Ensure `report_url` in Duplicacy Web UI points to `http://<exporter-host>:9750/webhook`. The exporter must be reachable from the Web UI container.

## Metrics show but labels are wrong or missing

- Set `LOG_LEVEL=DEBUG` to see how each log line is parsed and which labels are resolved.
- If storage targets show as raw IPs, use `STORAGE_HOST_MAP` to map them to friendly names.
- If machine name is missing, set `MACHINE_NAME` explicitly.

## Metrics (or HA sensors) disappear after restarting the exporter

- Persistence is on by default — confirm `STATE_FILE`'s directory is a **writable mounted volume** (default `/data`). Without a volume the state is lost when the container is re-created on an image upgrade.
- Check the logs for `Disabling metric persistence; cannot write …`: the directory isn't writable. Mount a volume or set `STATE_FILE` to a writable path.
- See [Persistence across restarts](configuration.md#persistence-across-restarts) for details.

## Docker socket permission denied

The exporter process runs as root inside the container by default. If you run it as a non-root user, ensure the user has access to the Docker socket (typically group `docker`, GID 999 or similar).

## Webhook returns 404

Verify the `WEBHOOK_PATH` environment variable matches the path you configured in Duplicacy Web UI. The default is `/webhook`.
