#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


SLEEVE_TO_CONFIG = {
    "etf_core_1k": "configs/etf_core_1k.json",
    "etf_breakout_1k": "configs/etf_breakout_1k.json",
    "etf_meanrev_1k": "configs/etf_meanrev_1k.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run main.py commands against an isolated sleeve config."
    )
    parser.add_argument(
        "--sleeve",
        choices=sorted(SLEEVE_TO_CONFIG.keys()),
        default=None,
        help="Sleeve name",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available sleeves and exit",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to pass to main.py (example: -- scan)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list:
        for sleeve, config in SLEEVE_TO_CONFIG.items():
            print(f"{sleeve} -> {config}")
        return
    if not args.sleeve:
        raise SystemExit("Provide --sleeve (or use --list).")

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("Provide a command after --, e.g. -- scan")

    config_path = SLEEVE_TO_CONFIG[args.sleeve]
    cmd = ["uv", "run", "python", "main.py", "--config", config_path, *command]
    print("running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
