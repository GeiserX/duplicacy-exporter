# Storage poller

The Web UI webhook cannot carry storage size or revision counts. The optional
storage poller, off by default, fills that gap by running the duplicacy CLI on a
schedule:

- `duplicacy -log list -all` → revision count and latest revision per snapshot id
- `duplicacy -log check -tabular -stats` → total chunk count and total storage size

Enable it with `POLLER_ENABLED=true` and a `POLLER_REPOSITORIES` JSON list:

```yaml
environment:
  - POLLER_ENABLED=true
  - POLLER_INTERVAL=86400          # once a day
  - POLLER_REPOSITORIES=[{"path":"/repos/photos","storage":"offsite","snapshot_id":"photos"}]
volumes:
  - /srv/duplicacy/photos:/repos/photos   # an initialised duplicacy repository
```

!!! warning "Security and cost"
    The poller runs the `duplicacy` binary against your storage. It needs the binary (bundled in the image),
    the storage credentials and an initialised repository inside the exporter container: mount the
    repository's `.duplicacy` directory or pass the credentials in the environment. That is why it is off by
    default. `duplicacy check` lists every chunk, which is slow and can cost money on remote storage, so keep
    `POLLER_INTERVAL` large. The exporter works without the poller; the bundled binary only enables it.

## What lives where

| You want… | Use |
|-----------|-----|
| Per-run speed, progress, files, uploaded bytes | `log_tail` or `webhook` |
| Storage size + revision counts | poller (not in the webhook) |
| Prune completion tracking | `log_tail` (not in the webhook, not in the poller) |

The storage-size value is **approximate**: Duplicacy's `check` prints sizes in a
lossy human format (e.g. `5,120M`), which the exporter converts back to bytes.
