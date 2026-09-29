# Prometheus and Grafana

## Prometheus configuration

Add the exporter as a scrape target:

```yaml
scrape_configs:
  - job_name: "duplicacy"
    static_configs:
      - targets: ["duplicacy-exporter:9750"]
        labels:
          instance: "my-server"
```

## Example alerting rule

```yaml
groups:
  - name: duplicacy
    rules:
      - alert: DuplicacyBackupFailed
        expr: duplicacy_backup_last_exit_code != 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Duplicacy backup failed for {{ $labels.snapshot_id }}"

      - alert: DuplicacyBackupStale
        expr: time() - duplicacy_backup_last_success_timestamp_seconds > 86400
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "No successful Duplicacy backup in 24h for {{ $labels.snapshot_id }}"
```

## Grafana dashboard

A ready-to-import dashboard is included in [`dashboard.json`](../dashboard.json) and published on [Grafana.com (#25089)](https://grafana.com/grafana/dashboards/25089).

Import it in Grafana via **Dashboards → Import → Upload JSON file** or use the dashboard ID `25089`.
