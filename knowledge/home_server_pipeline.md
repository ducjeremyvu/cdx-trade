# Home Server Pipeline Plan

## Objective

Keep code on Git, move bulky generated data to run folders on the server, and pull only generated artifacts to the MacBook for review.

## Folder layout

Server writes nightly runs under:

`data/server_runs/<RUN_ID>/`

Each run contains:

- `reports/` (scan, daily, ops, go-live markdown)
- `backtests/` (30/90/180 setup backtests)
- `portfolio/` (constrained and unconstrained account backtests)
- `queue/` (signal queue snapshots)
- `logs/` (command logs)
- `manifest.json` (run metadata, size, key portfolio stats)

## Scripts

- Server pipeline: `scripts/home_server/run_nightly.sh`
- Manifest builder: `scripts/home_server/make_manifest.py`
- Retention pruner: `scripts/home_server/prune_runs.py`
- Mac fetch script: `scripts/home_server/fetch_runs.sh`

## Automation

Systemd templates are in:

- `scripts/home_server/systemd/cdx-trade-nightly.service`
- `scripts/home_server/systemd/cdx-trade-nightly.timer`

Install example on server:

```bash
sudo cp scripts/home_server/systemd/cdx-trade-nightly.service /etc/systemd/system/
sudo cp scripts/home_server/systemd/cdx-trade-nightly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cdx-trade-nightly.timer
```

## Mac pull workflow

```bash
REMOTE=user@10.0.0.12 REMOTE_ROOT=/home/user/cdx-trade/data/server_runs \
  /Users/ducjeremyvu/cdx-trade/scripts/home_server/fetch_runs.sh
```

Pulled data lands in:

`data/server_runs_remote/`

Pull metadata lands in:

`data/server_runs_remote/_meta/pull_history.tsv`

Columns:

`pull_timestamp_utc`, `remote`, `remote_root`, `run_count`, `latest_run_id`, `latest_size_mb`

## Tidy / bloat controls

1. Keep generated data out of Git.
2. Keep short retention windows by default (`KEEP_DAYS=30`, `KEEP_MAX_RUNS=120`).
3. Use one run folder per execution so cleanup is simple and deterministic.
4. Use `manifest.json` for each run and monitor `size_mb`.

## Ballpark storage sizing

If one run is `X` MB from manifest:

- Daily runs/year: `X * 365 MB`
- Weekday runs/year: `X * 260 MB`

Examples:

- 20 MB/run -> ~5.1 GB/year (weekdays)
- 50 MB/run -> ~12.7 GB/year (weekdays)
- 100 MB/run -> ~25.4 GB/year (weekdays)

Retention caps keep this bounded regardless of yearly totals.
