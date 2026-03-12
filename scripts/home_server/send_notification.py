#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send nightly pipeline notification email.")
    parser.add_argument("--run-dir", required=True, help="Run directory path")
    parser.add_argument("--run-id", required=True, help="Run ID")
    parser.add_argument("--status", required=True, choices=["ok", "error"], help="Pipeline status")
    parser.add_argument("--failed-step", default="", help="Last step name")
    return parser.parse_args()


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_metric(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def build_body(args: argparse.Namespace) -> str:
    run_dir = Path(args.run_dir)
    report_dir = run_dir / "reports"
    ops_text = read_text(report_dir / "ops.md")
    go_live_text = read_text(report_dir / "go_live_snapshot.md")
    daily_text = read_text(next(iter(report_dir.glob("*_daily.md")), report_dir / "missing.md"))

    manifest = {}
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    lines: list[str] = []
    lines.append(f"run_id: {args.run_id}")
    lines.append(f"status: {args.status}")
    lines.append(f"failed_step: {args.failed_step}")
    lines.append(f"run_dir: {args.run_dir}")
    lines.append("")
    lines.append("ops_snapshot:")
    for key in (
        "open_exposure_usd",
        "open_risk_to_stops_usd",
        "time_stop_due",
        "momentum_exit_due",
        "pending_signals",
        "pending_reviews",
        "fetch_status",
        "run_staleness_days",
    ):
        lines.append(f"- {key}: {extract_metric(ops_text, key) or 'n/a'}")
    lines.append("")
    lines.append("go_live_snapshot:")
    for key in ("go_live_ready", "projected_monthly_net_usd"):
        lines.append(f"- {key}: {extract_metric(go_live_text, key) or 'n/a'}")
    lines.append("")
    lines.append("daily_snapshot:")
    for key in ("open_trades", "signals_created", "time_stop_due"):
        lines.append(f"- {key}: {extract_metric(daily_text, f'- {key}') or 'n/a'}")
    lines.append("")
    lines.append("manifest_profiles:")
    for profile in ("constrained", "constrained_capacity3", "unconstrained"):
        data = manifest.get("portfolio", {}).get(profile, {})
        if not data:
            lines.append(f"- {profile}: n/a")
            continue
        lines.append(
            f"- {profile}: trades={data.get('trades', 0)} "
            f"avg_r={data.get('avg_r', 0):.2f} "
            f"win_rate={data.get('win_rate', 0):.2f} "
            f"cum_r={data.get('cum_r', 0):.2f}"
        )
    lines.append("")
    lines.append("logs:")
    lines.append(f"- {run_dir / 'logs'}")
    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_to = os.getenv("SMTP_TO", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_to
    if not smtp_host or not smtp_to:
        print("notification_skipped: SMTP_HOST/SMTP_TO not configured")
        return

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "y"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = smtp_to
    message.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        if smtp_use_tls:
            server.starttls()
        if smtp_username:
            server.login(smtp_username, smtp_password)
        server.send_message(message)
    print("notification_sent: email")


def main() -> None:
    args = parse_args()
    status_word = "SUCCESS" if args.status == "ok" else "FAILURE"
    subject = f"[cdx-trade] nightly {status_word} {args.run_id}"
    body = build_body(args)
    send_email(subject, body)


if __name__ == "__main__":
    main()
