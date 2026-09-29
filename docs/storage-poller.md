# Storage poller (optional)

The Web UI webhook **cannot** carry storage size or revision counts. The optional
storage poller fills that gap by periodically running the duplicacy CLI:

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

> **⚠️ Security & cost.** The poller **runs the `duplicacy` binary against your
> storage**, so it needs the binary (bundled in the image) **plus storage
> credentials and an initialised repository inside the exporter container**
> (mount the repo's `.duplicacy` directory or provide credentials via the
> environment). It is **opt-in and off by default** for this reason. `check` can
> be **slow and costly** on remote storage (it lists every chunk), so keep
> `POLLER_INTERVAL` large. The exporter still runs fine without the poller — the
> bundled binary simply enables it.

## What lives where

| You want… | Use |
|-----------|-----|
| Per-run speed, progress, files, uploaded bytes | `log_tail` **or** `webhook` |
| **Storage size** + **revision counts** | **poller** (not in the webhook) |
| **Prune** completion tracking | `log_tail` (not in the webhook, not in the poller) |

The storage-size value is **approximate**: Duplicacy's `check` prints sizes in a
lossy human format (e.g. `5,120M`), which the exporter converts back to bytes.
