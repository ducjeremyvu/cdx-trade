#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


MODE_TO_SLOTS = {
    "baseline2": 2,
    "growth3": 3,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set slot mode by updating max_open_positions in config.json."
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODE_TO_SLOTS.keys()),
        help="Named slot mode to apply",
    )
    parser.add_argument(
        "--slots",
        type=int,
        help="Explicit max_open_positions value (overrides --mode)",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.slots is None and args.mode is None:
        raise SystemExit("Provide --mode or --slots.")

    target_slots = args.slots if args.slots is not None else MODE_TO_SLOTS[args.mode]
    if target_slots <= 0:
        raise SystemExit(f"--slots must be > 0, got {target_slots}")

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    old_slots = int(config.get("max_open_positions", 1))
    config["max_open_positions"] = int(target_slots)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    applied_mode = args.mode or f"custom:{target_slots}"
    print(f"slot_mode: {applied_mode}")
    print(f"max_open_positions: {old_slots} -> {target_slots}")


if __name__ == "__main__":
    main()
