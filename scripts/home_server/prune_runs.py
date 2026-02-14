from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_run_ts(name: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H%M%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(name, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune old run directories")
    parser.add_argument("--root", required=True)
    parser.add_argument("--keep-days", type=int, default=30)
    parser.add_argument("--keep-max-runs", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        return

    runs: list[tuple[datetime, Path]] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        ts = parse_run_ts(path.name)
        if ts is None:
            continue
        runs.append((ts, path))

    runs.sort(key=lambda item: item[0], reverse=True)
    keep_cutoff = datetime.now(timezone.utc) - timedelta(days=args.keep_days)

    for idx, (ts, path) in enumerate(runs):
        keep_by_count = idx < args.keep_max_runs
        keep_by_age = ts >= keep_cutoff
        if keep_by_count or keep_by_age:
            continue
        shutil.rmtree(path, ignore_errors=True)
        print(f"pruned {path}")


if __name__ == "__main__":
    main()
