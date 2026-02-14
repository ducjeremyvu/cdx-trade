from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def dir_size_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def read_trade_stats(path: Path) -> dict:
    if not path.exists():
        return {"trades": 0, "avg_r": 0.0, "win_rate": 0.0, "cum_r": 0.0}
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return {"trades": 0, "avg_r": 0.0, "win_rate": 0.0, "cum_r": 0.0}
    if df.empty or "r_multiple" not in df.columns:
        return {"trades": 0, "avg_r": 0.0, "win_rate": 0.0, "cum_r": 0.0}
    r = pd.to_numeric(df["r_multiple"], errors="coerce").dropna()
    if r.empty:
        return {"trades": 0, "avg_r": 0.0, "win_rate": 0.0, "cum_r": 0.0}
    return {
        "trades": int(len(r)),
        "avg_r": float(r.mean()),
        "win_rate": float((r > 0).mean()),
        "cum_r": float(r.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build run manifest for nightly server job")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out = Path(args.out)

    constrained = read_trade_stats(run_dir / "portfolio" / "trades_constrained.csv")
    unconstrained = read_trade_stats(run_dir / "portfolio" / "trades_unconstrained.csv")
    total_bytes = dir_size_bytes(run_dir)

    manifest = {
        "run_id": args.run_id,
        "run_dir": str(run_dir),
        "size_bytes": total_bytes,
        "size_mb": round(total_bytes / (1024 * 1024), 2),
        "est_yearly_gb_daily_runs": round((total_bytes * 365) / (1024**3), 2),
        "portfolio": {
            "constrained": constrained,
            "unconstrained": unconstrained,
        },
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
