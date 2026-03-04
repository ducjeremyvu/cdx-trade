#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


PHASE_COMMANDS = {
    "open": [
        ["uv", "run", "python", "main.py", "sync", "--limit", "100"],
        ["uv", "run", "python", "scripts/run_multi_sleeve.py", "--execute", "--ignore-rejects"],
        ["uv", "run", "python", "main.py", "ops-report"],
    ],
    "midday": [
        ["uv", "run", "python", "main.py", "sync", "--limit", "100"],
        ["uv", "run", "python", "scripts/run_multi_sleeve.py", "--execute", "--ignore-rejects"],
        ["uv", "run", "python", "main.py", "ops-report"],
    ],
    "close": [
        ["uv", "run", "python", "main.py", "sync", "--limit", "100"],
        ["uv", "run", "python", "main.py", "daily-report"],
        ["uv", "run", "python", "main.py", "ops-report"],
        ["uv", "run", "python", "main.py", "go-live-snapshot"],
        ["uv", "run", "python", "main.py", "analyze-latest-run", "--root", "data/server_runs_remote"],
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled trading cadence tasks.")
    parser.add_argument(
        "--phase",
        choices=["open", "midday", "close", "full"],
        required=True,
        help="Cadence phase to run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    return parser.parse_args()


def run_phase(phase: str, dry_run: bool) -> int:
    commands = PHASE_COMMANDS[phase]
    for cmd in commands:
        print("running:", " ".join(cmd))
        if dry_run:
            continue
        rc = subprocess.run(cmd, check=False).returncode
        if rc != 0:
            print(f"failed: rc={rc} cmd={' '.join(cmd)}")
            return rc
    return 0


def main() -> None:
    args = parse_args()
    phases = ["open", "midday", "close"] if args.phase == "full" else [args.phase]
    for phase in phases:
        print(f"\n== phase: {phase} ==")
        rc = run_phase(phase, args.dry_run)
        if rc != 0:
            raise SystemExit(rc)
    print("\ncadence_complete")


if __name__ == "__main__":
    main()
