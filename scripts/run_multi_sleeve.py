#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpaca_client import AlpacaClient
from config import AppConfig


DEFAULT_SLEEVES = [
    "configs/etf_core_1k.json",
    "configs/etf_breakout_1k.json",
    "configs/etf_meanrev_1k.json",
    "configs/equity_core_1k.json",
    "configs/volatility_etf_1k.json",
]


@dataclass
class PendingSignal:
    config_path: str
    sleeve_id: str
    signal_id: str
    symbol: str
    setup_name: str
    created_ts: str
    recommendation: str = "unknown"
    avg_r_180: float = -999.0
    assess_note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run multi-sleeve cycle: sync, scan, assess pending signals, "
            "and optionally auto-approve."
        )
    )
    parser.add_argument(
        "--sleeves",
        default=",".join(DEFAULT_SLEEVES),
        help="Comma-separated config paths",
    )
    parser.add_argument(
        "--max-new-approvals-total",
        type=int,
        default=2,
        help="Global cap for new approvals in this run",
    )
    parser.add_argument(
        "--max-new-approvals-per-sleeve",
        type=int,
        default=1,
        help="Per-sleeve cap for new approvals in this run",
    )
    parser.add_argument(
        "--aggressive",
        action="store_true",
        help="Raise approval caps for faster data collection",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute approve/ignore actions. Default is dry-run.",
    )
    parser.add_argument(
        "--ignore-rejects",
        action="store_true",
        help="Mark rejected recommendations as ignored",
    )
    return parser.parse_args()


def run_main(config_path: str, command: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, "main.py", "--config", config_path, *command]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_pending_signals(config_path: str, signal_queue_path: str, sleeve_id: str) -> list[PendingSignal]:
    p = Path(signal_queue_path)
    if not p.exists():
        return []
    rows: list[PendingSignal] = []
    with p.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "pending":
                continue
            rows.append(
                PendingSignal(
                    config_path=config_path,
                    sleeve_id=sleeve_id,
                    signal_id=row["signal_id"],
                    symbol=row["symbol"],
                    setup_name=row.get("setup_name", ""),
                    created_ts=row.get("created_ts", ""),
                )
            )
    return rows


def parse_assess_metrics(markdown_path: str) -> tuple[float, str]:
    avg_r_180 = -999.0
    note = ""
    try:
        text = Path(markdown_path).read_text(encoding="utf-8")
    except Exception as exc:
        return avg_r_180, f"read_error={exc}"
    m = re.search(r"avg_r_180=([-+]?[0-9]*\.?[0-9]+)", text)
    if m:
        avg_r_180 = float(m.group(1))
    hm = re.search(r"hot_ratio=([-+]?[0-9]*\.?[0-9]+)", text)
    if hm:
        note = f"hot_ratio={hm.group(1)}"
    return avg_r_180, note


def assess_signal(signal: PendingSignal) -> PendingSignal:
    with tempfile.NamedTemporaryFile(prefix="assess_multi_", suffix=".md", delete=False) as tmp:
        output_path = tmp.name
    rc, out = run_main(
        signal.config_path,
        ["assess-multi", "--signal-id", signal.signal_id, "--output", output_path],
    )
    if rc != 0:
        signal.recommendation = "error"
        signal.assess_note = "assess_failed"
        return signal
    rm = re.search(r"recommendation:\s*(\w+)", out)
    signal.recommendation = rm.group(1).strip().lower() if rm else "unknown"
    avg_r_180, note = parse_assess_metrics(output_path)
    signal.avg_r_180 = avg_r_180
    signal.assess_note = note
    return signal


def get_live_blocked_symbols() -> set[str]:
    cfg = AppConfig.from_env()
    client = AlpacaClient(cfg)
    blocked: set[str] = set()
    for p in client.list_open_positions():
        blocked.add(str(getattr(p, "symbol", "")).upper())
    for o in client.list_recent_orders(limit=200, status="open"):
        blocked.add(str(getattr(o, "symbol", "")).upper())
    return {s for s in blocked if s}


def main() -> None:
    args = parse_args()
    if args.aggressive:
        args.max_new_approvals_total = max(args.max_new_approvals_total, 4)
        args.max_new_approvals_per_sleeve = max(args.max_new_approvals_per_sleeve, 2)
    sleeve_paths = [s.strip() for s in args.sleeves.split(",") if s.strip()]
    blocked_symbols = get_live_blocked_symbols()
    print("blocked_symbols_live:", ",".join(sorted(blocked_symbols)) if blocked_symbols else "none")

    all_pending: list[PendingSignal] = []
    for config_path in sleeve_paths:
        cfg = load_config(config_path)
        sleeve_id = cfg.get("sleeve_id", Path(config_path).stem)
        print(f"\n== sleeve {sleeve_id} ({config_path}) ==")
        for command in (["sync", "--limit", "100"], ["scan"]):
            rc, out = run_main(config_path, command)
            line = out.strip().splitlines()[-1] if out.strip() else ""
            print(f"{' '.join(command)} -> rc={rc} {line}")
        pending = load_pending_signals(
            config_path=config_path,
            signal_queue_path=cfg["signal_queue_path"],
            sleeve_id=sleeve_id,
        )
        print(f"pending_signals={len(pending)}")
        all_pending.extend(pending)

    assessed = [assess_signal(s) for s in all_pending]
    approved_candidates = [s for s in assessed if s.recommendation == "approve"]
    rejected_candidates = [s for s in assessed if s.recommendation == "reject"]

    # Prefer stronger 180d expectancy first.
    approved_candidates.sort(key=lambda s: (s.avg_r_180, s.created_ts), reverse=True)
    selected: list[PendingSignal] = []
    used_symbols = set(blocked_symbols)
    sleeve_counts: dict[str, int] = {}
    for signal in approved_candidates:
        if len(selected) >= args.max_new_approvals_total:
            break
        if signal.symbol.upper() in used_symbols:
            continue
        if sleeve_counts.get(signal.sleeve_id, 0) >= args.max_new_approvals_per_sleeve:
            continue
        selected.append(signal)
        used_symbols.add(signal.symbol.upper())
        sleeve_counts[signal.sleeve_id] = sleeve_counts.get(signal.sleeve_id, 0) + 1

    print("\n== recommendations ==")
    for s in assessed:
        print(
            f"{s.sleeve_id} {s.symbol} {s.setup_name} "
            f"signal_id={s.signal_id} rec={s.recommendation} avg_r_180={s.avg_r_180:.2f}"
        )

    print("\n== selected approvals ==")
    if not selected:
        print("none")
    for s in selected:
        print(
            f"{s.sleeve_id} {s.symbol} signal_id={s.signal_id} "
            f"avg_r_180={s.avg_r_180:.2f}"
        )

    if not args.execute:
        print("\ndry-run only (pass --execute to apply approvals/ignores).")
        return

    for s in selected:
        reason = (
            f"multi-sleeve allocator approve avg_r_180={s.avg_r_180:.2f} "
            f"note={s.assess_note or 'na'}"
        )
        rc, out = run_main(
            s.config_path,
            ["approve-signal", "--signal-id", s.signal_id, "--reason", reason],
        )
        line = out.strip().splitlines()[-1] if out.strip() else ""
        print(f"approve {s.sleeve_id} {s.symbol} -> rc={rc} {line}")

    if args.ignore_rejects:
        for s in rejected_candidates:
            rc, out = run_main(
                s.config_path,
                ["ignore-signal", "--signal-id", s.signal_id, "--reason", "assess-multi reject"],
            )
            line = out.strip().splitlines()[-1] if out.strip() else ""
            print(f"ignore {s.sleeve_id} {s.symbol} -> rc={rc} {line}")


if __name__ == "__main__":
    main()
