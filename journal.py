from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from alpaca_client import AlpacaOrderResult


FIELDNAMES = [
    "trade_id",
    "order_id",
    "exit_order_id",
    "symbol",
    "direction",
    "setup_name",
    "entry_ts",
    "entry_price",
    "exit_ts",
    "exit_price",
    "entry_reason",
    "invalidation_reason",
    "stop_loss_logic",
    "take_profit_logic",
    "market_context",
    "emotional_state",
    "outcome",
    "r_multiple",
    "exit_reason",
    "what_went_right",
    "what_went_wrong",
    "improvement_idea",
]

NO_TRADE_FIELDNAMES = [
    "log_id",
    "symbol",
    "timestamp",
    "reason",
    "market_context",
    "emotional_state",
    "notes",
]

PENDING_REVIEW_FIELDNAMES = [
    "trade_id",
    "outcome",
    "r_multiple",
    "exit_reason",
    "what_went_right",
    "what_went_wrong",
    "improvement_idea",
]

REVIEW_QUEUE_FIELDNAMES = [
    "trade_id",
    "symbol",
    "exit_ts",
    "exit_price",
]

SIGNAL_QUEUE_FIELDNAMES = [
    "signal_id",
    "created_ts",
    "symbol",
    "direction",
    "setup_name",
    "entry_reason",
    "invalidation_reason",
    "stop_loss_logic",
    "take_profit_logic",
    "market_context",
    "emotional_state",
    "order_type",
    "limit_price",
    "qty",
    "status",
    "decision_ts",
    "decision_reason",
]


def init_journal(journal_path: str) -> None:
    dir_name = os.path.dirname(journal_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    if os.path.exists(journal_path):
        ensure_schema(journal_path)
        return
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()


def init_no_trade_journal(journal_path: str) -> None:
    dir_name = os.path.dirname(journal_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    if os.path.exists(journal_path):
        return
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=NO_TRADE_FIELDNAMES)
        writer.writeheader()


def init_pending_reviews(journal_path: str) -> None:
    dir_name = os.path.dirname(journal_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    if os.path.exists(journal_path):
        return
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PENDING_REVIEW_FIELDNAMES)
        writer.writeheader()


def init_review_queue(journal_path: str) -> None:
    dir_name = os.path.dirname(journal_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    if os.path.exists(journal_path):
        return
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_QUEUE_FIELDNAMES)
        writer.writeheader()


def init_signal_queue(journal_path: str) -> None:
    dir_name = os.path.dirname(journal_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    if os.path.exists(journal_path):
        return
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SIGNAL_QUEUE_FIELDNAMES)
        writer.writeheader()


def log_entry(journal_path: str, idea: dict, order: AlpacaOrderResult) -> str:
    trade_id = str(uuid4())
    entry_price = order.filled_avg_price or order.limit_price
    entry_ts = order.created_at or datetime.now(timezone.utc).isoformat()

    row = {
        "trade_id": trade_id,
        "order_id": order.order_id,
        "exit_order_id": "",
        "symbol": idea["symbol"],
        "direction": idea["direction"],
        "setup_name": idea["setup_name"],
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "exit_ts": "",
        "exit_price": "",
        "entry_reason": idea["entry_reason"],
        "invalidation_reason": idea["invalidation_reason"],
        "stop_loss_logic": idea["stop_loss_logic"],
        "take_profit_logic": idea["take_profit_logic"],
        "market_context": idea["market_context"],
        "emotional_state": idea["emotional_state"],
        "outcome": "",
        "r_multiple": "",
        "exit_reason": "",
        "what_went_right": "",
        "what_went_wrong": "",
        "improvement_idea": "",
    }

    append_row(journal_path, row)
    return trade_id


def log_exit(
    journal_path: str,
    trade_id: str,
    exit_ts: str,
    exit_price: float,
    outcome: str,
    r_multiple: float,
    exit_reason: str,
    what_went_right: str,
    what_went_wrong: str,
    improvement_idea: str,
    exit_order_id: str = "",
) -> None:
    rows = list(read_rows(journal_path))
    updated = False
    for row in rows:
        if row["trade_id"] == trade_id:
            row["exit_ts"] = exit_ts
            row["exit_price"] = exit_price
            if exit_order_id:
                row["exit_order_id"] = exit_order_id
            row["outcome"] = outcome
            row["r_multiple"] = r_multiple
            row["exit_reason"] = exit_reason
            row["what_went_right"] = what_went_right
            row["what_went_wrong"] = what_went_wrong
            row["improvement_idea"] = improvement_idea
            updated = True
            break

    if not updated:
        raise RuntimeError(f"Trade ID not found: {trade_id}")

    write_rows(journal_path, rows)


def append_row(journal_path: str, row: dict) -> None:
    with open(journal_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writerow(row)


def read_rows(journal_path: str) -> Iterable[dict]:
    with open(journal_path, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            yield row


def write_rows(journal_path: str, rows: Iterable[dict]) -> None:
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def ensure_schema(journal_path: str) -> None:
    with open(journal_path, "r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader, [])

    if not header:
        return

    missing = [field for field in FIELDNAMES if field not in header]
    if not missing:
        return

    rows = list(read_rows(journal_path))
    for row in rows:
        for field in missing:
            row[field] = ""

    write_rows(journal_path, rows)


def sync_entry_prices(journal_path: str, orders: list[dict]) -> int:
    rows = list(read_rows(journal_path))
    updated = 0
    orders_by_id = {order["order_id"]: order for order in orders}
    for row in rows:
        order_id = row.get("order_id")
        if not order_id and row.get("entry_ts"):
            try:
                entry_ts = datetime.fromisoformat(row["entry_ts"])
            except ValueError:
                entry_ts = None
            if entry_ts:
                candidates = [
                    order
                    for order in orders
                    if order["symbol"] == row.get("symbol")
                    and order.get("created_at")
                ]
                if candidates:
                    nearest = min(
                        candidates,
                        key=lambda order: abs(
                            (order["created_at"] - entry_ts).total_seconds()
                        ),
                    )
                    if abs((nearest["created_at"] - entry_ts).total_seconds()) <= 120:
                        row["order_id"] = nearest["order_id"]
                        order_id = nearest["order_id"]
        if row.get("entry_price"):
            continue
        order = orders_by_id.get(order_id) if order_id else None
        if not order:
            continue
        filled_avg_price = order.get("filled_avg_price")
        if filled_avg_price is None:
            continue
        row["entry_price"] = filled_avg_price
        updated += 1

    if updated:
        write_rows(journal_path, rows)
    return updated


def sync_exits(journal_path: str, orders: list[dict]) -> int:
    rows = list(read_rows(journal_path))
    updated_trade_ids = []
    for row in rows:
        if row.get("exit_ts"):
            continue
        entry_ts_raw = row.get("entry_ts")
        if not entry_ts_raw:
            continue
        try:
            entry_ts = datetime.fromisoformat(entry_ts_raw)
        except ValueError:
            continue
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        side_needed = "sell" if row.get("direction") == "long" else "buy"
        candidates = [
            order
            for order in orders
            if order["symbol"] == row.get("symbol")
            and order.get("side") == side_needed
            and order.get("filled_at")
            and order["filled_at"] >= entry_ts
            and order.get("filled_avg_price") is not None
        ]
        if not candidates:
            continue
        earliest = min(candidates, key=lambda order: order["filled_at"])
        row["exit_ts"] = earliest["filled_at"].isoformat()
        row["exit_price"] = earliest["filled_avg_price"]
        row["exit_order_id"] = earliest["order_id"]
        if not row.get("exit_reason"):
            row["exit_reason"] = "auto_sync"
        updated_trade_ids.append(row["trade_id"])

    if updated_trade_ids:
        write_rows(journal_path, rows)
    return updated_trade_ids


def log_no_trade(
    journal_path: str,
    symbol: str,
    reason: str,
    market_context: str,
    emotional_state: str,
    notes: str = "",
) -> str:
    log_id = str(uuid4())
    row = {
        "log_id": log_id,
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "market_context": market_context,
        "emotional_state": emotional_state,
        "notes": notes,
    }
    with open(journal_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=NO_TRADE_FIELDNAMES)
        writer.writerow(row)
    return log_id


def add_pending_review(
    journal_path: str,
    trade_id: str,
    outcome: str,
    r_multiple: float,
    exit_reason: str,
    what_went_right: str,
    what_went_wrong: str,
    improvement_idea: str,
) -> None:
    with open(journal_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PENDING_REVIEW_FIELDNAMES)
        writer.writerow(
            {
                "trade_id": trade_id,
                "outcome": outcome,
                "r_multiple": r_multiple,
                "exit_reason": exit_reason,
                "what_went_right": what_went_right,
                "what_went_wrong": what_went_wrong,
                "improvement_idea": improvement_idea,
            }
        )


def apply_pending_reviews(journal_path: str, pending_path: str) -> int:
    pending_rows = list(read_rows(pending_path))
    if not pending_rows:
        return 0
    rows = list(read_rows(journal_path))
    pending_by_id = {row["trade_id"]: row for row in pending_rows}
    applied = 0
    remaining = []
    for pending in pending_rows:
        trade_id = pending["trade_id"]
        match = next((row for row in rows if row["trade_id"] == trade_id), None)
        if not match or not match.get("exit_ts"):
            remaining.append(pending)
            continue
        if match.get("outcome"):
            applied += 1
            continue
        match["outcome"] = pending["outcome"]
        match["r_multiple"] = pending["r_multiple"]
        match["exit_reason"] = pending["exit_reason"]
        match["what_went_right"] = pending["what_went_right"]
        match["what_went_wrong"] = pending["what_went_wrong"]
        match["improvement_idea"] = pending["improvement_idea"]
        applied += 1
    if applied:
        write_rows(journal_path, rows)
    with open(pending_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PENDING_REVIEW_FIELDNAMES)
        writer.writeheader()
        writer.writerows(remaining)
    return applied


def enqueue_review(
    journal_path: str,
    trade_id: str,
    symbol: str,
    exit_ts: str,
    exit_price: float,
) -> None:
    existing = {row["trade_id"] for row in read_rows(journal_path)}
    if trade_id in existing:
        return
    with open(journal_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_QUEUE_FIELDNAMES)
        writer.writerow(
            {
                "trade_id": trade_id,
                "symbol": symbol,
                "exit_ts": exit_ts,
                "exit_price": exit_price,
            }
        )


def list_review_queue(journal_path: str) -> list[dict]:
    return list(read_rows(journal_path))


def enqueue_signal(
    journal_path: str,
    idea: dict,
    order_type: str,
    limit_price: float | None,
    qty: int,
) -> str:
    signal_id = str(uuid4())
    row = {
        "signal_id": signal_id,
        "created_ts": datetime.now(timezone.utc).isoformat(),
        "symbol": idea["symbol"],
        "direction": idea["direction"],
        "setup_name": idea["setup_name"],
        "entry_reason": idea["entry_reason"],
        "invalidation_reason": idea["invalidation_reason"],
        "stop_loss_logic": idea["stop_loss_logic"],
        "take_profit_logic": idea["take_profit_logic"],
        "market_context": idea["market_context"],
        "emotional_state": idea["emotional_state"],
        "order_type": order_type,
        "limit_price": limit_price if limit_price is not None else "",
        "qty": qty,
        "status": "pending",
        "decision_ts": "",
        "decision_reason": "",
    }
    with open(journal_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SIGNAL_QUEUE_FIELDNAMES)
        writer.writerow(row)
    return signal_id


def list_signal_queue(journal_path: str, status: str | None = None) -> list[dict]:
    rows = list(read_rows(journal_path))
    if status is None:
        return rows
    return [row for row in rows if row.get("status") == status]


def update_signal_status(
    journal_path: str,
    signal_id: str,
    status: str,
    decision_reason: str = "",
) -> dict:
    rows = list(read_rows(journal_path))
    updated = None
    for row in rows:
        if row.get("signal_id") == signal_id:
            row["status"] = status
            row["decision_ts"] = datetime.now(timezone.utc).isoformat()
            row["decision_reason"] = decision_reason
            updated = row
            break
    if not updated:
        raise RuntimeError(f"Signal ID not found: {signal_id}")
    with open(journal_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SIGNAL_QUEUE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return updated


def find_open_trade_id(journal_path: str, symbol: str) -> str | None:
    rows = list(read_rows(journal_path))
    open_trades = [
        row
        for row in rows
        if row.get("symbol") == symbol and not row.get("exit_ts")
    ]
    if not open_trades:
        return None
    return open_trades[-1]["trade_id"]


def count_open_trades(journal_path: str) -> int:
    rows = list(read_rows(journal_path))
    return sum(1 for row in rows if not row.get("exit_ts"))
