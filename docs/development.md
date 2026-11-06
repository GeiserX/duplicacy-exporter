# Development

The exporter is one file, `duplicacy_exporter.py`, with `prometheus_client` as its only runtime dependency.
Tests live in `tests/` and run with pytest.

## Run from source

```bash
git clone https://github.com/GeiserX/duplicacy-exporter.git && cd duplicacy-exporter
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
MODE=webhook STATE_FILE=/tmp/duplicacy-exporter-state.json python duplicacy_exporter.py
```

`STATE_FILE` defaults to `/data/...`, which does not exist outside the container; point it somewhere writable
or set `PERSIST_ENABLED=false`.

## Tests

```bash
pytest tests/
```

`tests/test_exporter.py` covers the log parser (every regex, the section headers, `DUPLICACY_META`), the
webhook handler and the storage poller's output parsing; `tests/test_persistence.py` covers the state file.
Add a test beside the code you change; a new log line shape gets a regex test with the exact line.

## Docs

The site is built with [Zensical](https://zensical.org/) from `docs/` and `zensical.toml`:

```bash
pip install -r docs/requirements-docs.txt
python -m zensical serve                    # http://127.0.0.1:8000
python -m zensical build --clean --strict
python -I .github/scripts/site-check.py site
```

Pages are Markdown under `docs/` and the nav is in `zensical.toml`. The `Docs` workflow runs the last two commands on every pull request and deploys `main` to GitHub Pages. The strict build fails on a broken link or anchor; `site-check.py` fails on what the build lets through: a page left out of the nav, a nav entry for a missing file, a missing image, a link rooted at `/`.
Screenshots are PNGs under `docs/images/screenshots/`, taken from a demo run with fake machine names.

## Release

1. Set the new version in `duplicacy_exporter.py` (`VERSION`), `pyproject.toml` (`version`), and the image
   tag in `README.md` and `docs/getting-started.md`. The root `docker-compose.yml` builds from source; its
   `# image: drumsergio/duplicacy-exporter:X.Y.Z` line is a comment, so update it or leave it.
2. Commit, tag `vX.Y.Z`, push the tag.
3. `pypi-publish.yml` builds and uploads the package; `docker-publish.yml` builds amd64 and arm64 images and
   pushes `drumsergio/duplicacy-exporter:X.Y.Z`; `dockerhub-description.yml` syncs the README to Docker Hub.
4. Write the GitHub release notes on the tag.

The dashboard is `dashboard.json` at the repo root. Edit it in Grafana, export with "Export for sharing
externally" so the datasource stays `${DS_PROMETHEUS}`, and update the listing on Grafana.com.
