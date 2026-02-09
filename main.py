import argparse
import csv
import os
import time
from datetime import datetime, timedelta, timezone
from datetime import date as date_cls

import pandas as pd

from alpaca_client import AlpacaClient
from backtest import (
    BacktestResult,
    run_backtest,
    summarize_backtest,
    run_recent_backtest,
    write_backtest_rollup,
)
from config import AppConfig
from journal import (
    init_journal,
    init_no_trade_journal,
    init_pending_reviews,
    init_review_queue,
    init_signal_queue,
    log_entry,
    log_exit,
    log_no_trade,
    add_pending_review,
    sync_entry_prices,
    sync_exits,
    apply_pending_reviews,
    enqueue_review,
    list_review_queue,
    find_open_trade_id,
    enqueue_signal,
    list_signal_queue,
    update_signal_status,
    read_rows,
    count_open_trades,
)
from trade_logic import find_trade_idea
from review import (
    daily_summary,
    weekly_summary,
    write_weekly_snapshot,
    no_trade_summary,
)


def _regime_filter(config: AppConfig) -> dict:
    return {
        "enabled": config.regime_filter_enabled,
        "fast_sma": config.regime_fast_sma,
        "slow_sma": config.regime_slow_sma,
    }


def _read_universe(path: str) -> list[str]:
    symbols: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                symbols.append(raw.upper())
    except FileNotFoundError:
        raise RuntimeError(f"Universe file not found: {path}")
    return symbols


def build_order_list(client: AlpacaClient, limit: int) -> list[dict]:
    orders = client.list_recent_orders(limit=limit, status="closed")
    order_list = []
    for order in orders:
        created_at = order.created_at
        filled_at = order.filled_at
        filled_avg_price = (
            float(order.filled_avg_price) if order.filled_avg_price else None
        )
        order_list.append(
            {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "side": order.side.value if hasattr(order.side, "value") else order.side,
                "created_at": created_at,
                "filled_at": filled_at,
                "filled_avg_price": filled_avg_price,
            }
        )
    return order_list


def _allowed_setups_for_symbol(config: AppConfig, symbol: str) -> set[str] | None:
    enabled = set(config.enabled_setups) if config.enabled_setups else None
    symbol_key = symbol.upper()
    if symbol_key not in config.setups_by_symbol:
        return set() if config.allowlist_only else enabled
    symbol_setups = set(config.setups_by_symbol[symbol_key])
    if enabled is None:
        return symbol_setups
    return enabled & symbol_setups


def _passes_backtest_gate(
    client: AlpacaClient,
    config: AppConfig,
    symbol: str,
    setup_name: str,
) -> tuple[bool, str]:
    if config.backtest_gate_days <= 0:
        return True, ""
    output_path = (
        f"data/backtest_gate_{symbol}_{setup_name}_{config.backtest_gate_days}d.csv"
    )
    result = run_recent_backtest(
        client=client,
        symbol=symbol,
        recent_days=config.backtest_gate_days,
        risk_multiple=2.0,
        time_stop_days=5,
        output_path=output_path,
        setup_name=setup_name,
        regime_filter=_regime_filter(config),
    )
    if result.total_trades < config.backtest_gate_min_trades:
        return (
            False,
            (
                f"trades {result.total_trades} < "
                f"{config.backtest_gate_min_trades}"
            ),
        )
    if result.avg_r < config.backtest_gate_min_avg_r:
        return (
            False,
            f"avg_r {result.avg_r:.2f} < {config.backtest_gate_min_avg_r:.2f}",
        )
    if result.win_rate < config.backtest_gate_min_win_rate:
        return (
            False,
            (
                f"win_rate {result.win_rate:.2f} < "
                f"{config.backtest_gate_min_win_rate:.2f}"
            ),
        )
    return True, ""


def evaluate_and_trade(
    client: AlpacaClient,
    config: AppConfig,
    symbol: str,
    order_type: str,
    limit_price: float | None,
    no_trade_reason: str,
    no_trade_context: str,
    no_trade_emotion: str,
    no_trade_notes: str,
) -> str | None:
    if symbol.upper() in config.watch_only_symbols:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Watch-only symbol",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes="Symbol is configured as watch-only",
        )
        print(f"Watch-only symbol. Logged no-trade: log_id={log_id}")
        return None
    if count_open_trades(config.journal_path) >= config.max_open_positions:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Max open positions reached",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=f"max_open_positions={config.max_open_positions}",
        )
        print(f"Max open positions reached. Logged no-trade: log_id={log_id}")
        return None
    allowed_setups = _allowed_setups_for_symbol(config, symbol)
    idea = find_trade_idea(
        client,
        symbol,
        allowed_setups,
        regime_filter=_regime_filter(config),
    )
    if idea is None:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason=no_trade_reason,
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=no_trade_notes,
        )
        print(f"No trade idea found. Logged no-trade: log_id={log_id}")
        return None
    passed, gate_reason = _passes_backtest_gate(
        client, config, symbol, idea["setup_name"]
    )
    if not passed:
        notes = (
            f"Backtest gate failed ({config.backtest_gate_days}d): {gate_reason}"
        )
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Backtest gate failed",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=notes,
        )
        print(f"Backtest gate failed. Logged no-trade: log_id={log_id}")
        return None

    order = client.place_order(
        symbol=idea["symbol"],
        side="buy" if idea["direction"] == "long" else "sell",
        qty=config.fixed_position_size,
        order_type=order_type,
        limit_price=limit_price,
    )

    trade_id = log_entry(
        journal_path=config.journal_path,
        idea=idea,
        order=order,
    )
    print(f"Logged entry: trade_id={trade_id}")
    return trade_id


def evaluate_and_queue(
    client: AlpacaClient,
    config: AppConfig,
    symbol: str,
    order_type: str,
    limit_price: float | None,
    no_trade_reason: str,
    no_trade_context: str,
    no_trade_emotion: str,
    no_trade_notes: str,
) -> str | None:
    if symbol.upper() in config.watch_only_symbols:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Watch-only symbol",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes="Symbol is configured as watch-only",
        )
        print(f"Watch-only symbol. Logged no-trade: log_id={log_id}")
        return None
    if count_open_trades(config.journal_path) >= config.max_open_positions:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Max open positions reached",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=f"max_open_positions={config.max_open_positions}",
        )
        print(f"Max open positions reached. Logged no-trade: log_id={log_id}")
        return None
    allowed_setups = _allowed_setups_for_symbol(config, symbol)
    idea = find_trade_idea(
        client,
        symbol,
        allowed_setups,
        regime_filter=_regime_filter(config),
    )
    if idea is None:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason=no_trade_reason,
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=no_trade_notes,
        )
        print(f"No trade idea found. Logged no-trade: log_id={log_id}")
        return None
    passed, gate_reason = _passes_backtest_gate(
        client, config, symbol, idea["setup_name"]
    )
    if not passed:
        notes = (
            f"Backtest gate failed ({config.backtest_gate_days}d): {gate_reason}"
        )
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Backtest gate failed",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=notes,
        )
        print(f"Backtest gate failed. Logged no-trade: log_id={log_id}")
        return None

    signal_id = enqueue_signal(
        config.signal_queue_path,
        idea=idea,
        order_type=order_type,
        limit_price=limit_price,
        qty=config.fixed_position_size,
    )
    print(f"Signal queued: signal_id={signal_id}")
    print(
        "signal_details:"
        f" symbol={idea['symbol']}"
        f" direction={idea['direction']}"
        f" setup={idea['setup_name']}"
        f" order_type={order_type}"
        f" limit_price={limit_price}"
        f" qty={config.fixed_position_size}"
    )
    print(f"entry_reason: {idea['entry_reason']}")
    print(f"invalidation_reason: {idea['invalidation_reason']}")
    print(f"stop_loss_logic: {idea['stop_loss_logic']}")
    print(f"take_profit_logic: {idea['take_profit_logic']}")
    print(f"market_context: {idea['market_context']}")
    print(f"emotional_state: {idea['emotional_state']}")
    return signal_id


def handle_trade(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    evaluate_and_trade(
        client,
        config,
        args.symbol,
        args.order_type,
        args.limit_price,
        args.no_trade_reason,
        args.no_trade_context,
        args.no_trade_emotion,
        args.no_trade_notes,
    )


def handle_signal(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    evaluate_and_queue(
        client,
        config,
        args.symbol,
        args.order_type,
        args.limit_price,
        args.no_trade_reason,
        args.no_trade_context,
        args.no_trade_emotion,
        args.no_trade_notes,
    )


def handle_log_exit(config: AppConfig, args: argparse.Namespace) -> None:
    exit_ts = args.exit_ts or datetime.now(timezone.utc).isoformat()
    log_exit(
        journal_path=config.journal_path,
        trade_id=args.trade_id,
        exit_ts=exit_ts,
        exit_price=args.exit_price,
        outcome=args.outcome,
        r_multiple=args.r_multiple,
        exit_reason=args.exit_reason,
        what_went_right=args.what_went_right,
        what_went_wrong=args.what_went_wrong,
        improvement_idea=args.improvement_idea,
    )
    print(f"Logged exit: trade_id={args.trade_id}")


def handle_review(config: AppConfig, args: argparse.Namespace) -> None:
    if args.window == "daily":
        summary = daily_summary(
            config.journal_path, config.no_trade_journal_path, args.date
        )
    else:
        summary = weekly_summary(
            config.journal_path, config.no_trade_journal_path, args.date
        )
    for key, value in summary.items():
        print(f"{key}: {value}")


def handle_daily_report(config: AppConfig, args: argparse.Namespace) -> None:
    if args.date:
        if "T" in args.date:
            target_date = datetime.fromisoformat(args.date).date()
        else:
            target_date = date_cls.fromisoformat(args.date)
    else:
        target_date = datetime.now(timezone.utc).date()
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    summary = daily_summary(
        config.journal_path, config.no_trade_journal_path, target_date.isoformat()
    )
    no_trades = no_trade_summary(
        config.no_trade_journal_path, target_date.isoformat(), days=1
    )
    signals = list_signal_queue(config.signal_queue_path, status=None)
    signals_in_window = []
    for row in signals:
        created_ts = row.get("created_ts")
        if not created_ts:
            continue
        try:
            created_dt = datetime.fromisoformat(created_ts)
        except ValueError:
            continue
        if start <= created_dt < end:
            signals_in_window.append(row)

    status_counts: dict[str, int] = {}
    for row in signals_in_window:
        status = row.get("status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    lines = []
    lines.append(f"Daily report ({target_date.isoformat()})")
    lines.append("")
    lines.append("Trade summary")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("No-trade summary")
    lines.append("")
    for key, value in no_trades.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("Signal activity")
    lines.append("")
    lines.append(f"- signals_created: {len(signals_in_window)}")
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")
    if signals_in_window:
        lines.append("")
        lines.append("Signals")
        lines.append("")
        for row in signals_in_window:
            lines.append(
                "- {symbol} {direction} {setup} status={status} id={signal_id}".format(
                    symbol=row.get("symbol"),
                    direction=row.get("direction"),
                    setup=row.get("setup_name"),
                    status=row.get("status"),
                    signal_id=row.get("signal_id"),
                )
            )

    output_dir = args.output_dir
    output_path = (
        f"{output_dir}/{target_date.isoformat()}_daily.md"
    )
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))
    print(f"wrote_daily_report: {output_path}")


def handle_sync(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    order_list = build_order_list(client, args.limit)
    updated_entries = sync_entry_prices(config.journal_path, order_list)
    updated_trade_ids = sync_exits(config.journal_path, order_list)
    applied_reviews = apply_pending_reviews(
        config.journal_path, config.pending_reviews_path
    )
    if updated_trade_ids:
        rows = list_review_queue(config.review_queue_path)
        queued = {row["trade_id"] for row in rows}
        journal_rows = list(read_rows(config.journal_path))
        row_by_id = {row["trade_id"]: row for row in journal_rows}
        for trade_id in updated_trade_ids:
            if trade_id in queued:
                continue
            row = row_by_id.get(trade_id)
            if not row or row.get("outcome"):
                continue
            enqueue_review(
                config.review_queue_path,
                trade_id=trade_id,
                symbol=row["symbol"],
                exit_ts=row["exit_ts"],
                exit_price=row["exit_price"],
            )
    print(
        "Synced journal:"
        f" entry_prices={updated_entries} exit_fields={len(updated_trade_ids)}"
        f" applied_reviews={applied_reviews}"
    )


def handle_run_daily(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    buffer_minutes = args.buffer_minutes
    symbols = [
        value.strip()
        for value in (args.symbols or args.symbol).split(",")
        if value.strip()
    ]
    while True:
        order_list = build_order_list(client, args.sync_limit)
        updated_entries = sync_entry_prices(config.journal_path, order_list)
        updated_trade_ids = sync_exits(config.journal_path, order_list)
        applied_reviews = apply_pending_reviews(
            config.journal_path, config.pending_reviews_path
        )
        if updated_trade_ids:
            rows = list_review_queue(config.review_queue_path)
            queued = {row["trade_id"] for row in rows}
            journal_rows = list(read_rows(config.journal_path))
            row_by_id = {row["trade_id"]: row for row in journal_rows}
            for trade_id in updated_trade_ids:
                if trade_id in queued:
                    continue
                row = row_by_id.get(trade_id)
                if not row or row.get("outcome"):
                    continue
                enqueue_review(
                    config.review_queue_path,
                    trade_id=trade_id,
                    symbol=row["symbol"],
                    exit_ts=row["exit_ts"],
                    exit_price=row["exit_price"],
                )
                print(f"Review needed: trade_id={trade_id}")
        if updated_entries or updated_trade_ids or applied_reviews:
            print(
                "Synced journal:"
                f" entry_prices={updated_entries} exit_fields={len(updated_trade_ids)}"
                f" applied_reviews={applied_reviews}"
            )
        clock = client.get_clock()
        next_close = clock.next_close
        run_at = next_close + timedelta(minutes=buffer_minutes)
        now = datetime.now(timezone.utc)
        if run_at <= now:
            run_at = run_at + timedelta(days=1)
        sleep_seconds = max(0, (run_at - now).total_seconds())
        print(f"Next run at {run_at.isoformat()} (sleep {int(sleep_seconds)}s)")
        time.sleep(sleep_seconds)
        for symbol in symbols:
            if args.mode == "auto":
                evaluate_and_trade(
                    client,
                    config,
                    symbol,
                    args.order_type,
                    args.limit_price,
                    args.no_trade_reason,
                    args.no_trade_context,
                    args.no_trade_emotion,
                    args.no_trade_notes,
                )
            else:
                evaluate_and_queue(
                    client,
                    config,
                    symbol,
                    args.order_type,
                    args.limit_price,
                    args.no_trade_reason,
                    args.no_trade_context,
                    args.no_trade_emotion,
                    args.no_trade_notes,
                )
        if args.weekly_snapshot:
            now = datetime.now(timezone.utc)
            if now.weekday() == args.weekly_snapshot_day:
                path = write_weekly_snapshot(
                    config.journal_path,
                    config.no_trade_journal_path,
                    now.date().isoformat(),
                    args.weekly_snapshot_dir,
                )
                print(f"wrote_weekly_snapshot: {path}")


def handle_run_sync(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    while True:
        order_list = build_order_list(client, args.limit)
        updated_entries = sync_entry_prices(config.journal_path, order_list)
        updated_trade_ids = sync_exits(config.journal_path, order_list)
        applied_reviews = apply_pending_reviews(
            config.journal_path, config.pending_reviews_path
        )
        if updated_trade_ids:
            rows = list_review_queue(config.review_queue_path)
            queued = {row["trade_id"] for row in rows}
            journal_rows = list(read_rows(config.journal_path))
            row_by_id = {row["trade_id"]: row for row in journal_rows}
            for trade_id in updated_trade_ids:
                if trade_id in queued:
                    continue
                row = row_by_id.get(trade_id)
                if not row or row.get("outcome"):
                    continue
                enqueue_review(
                    config.review_queue_path,
                    trade_id=trade_id,
                    symbol=row["symbol"],
                    exit_ts=row["exit_ts"],
                    exit_price=row["exit_price"],
                )
                print(f"Review needed: trade_id={trade_id}")
        print(
            "Synced journal:"
            f" entry_prices={updated_entries} exit_fields={len(updated_trade_ids)}"
            f" applied_reviews={applied_reviews}"
        )
        time.sleep(args.interval_minutes * 60)


def handle_run_once(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    symbols = [
        value.strip()
        for value in (args.symbols or args.symbol).split(",")
        if value.strip()
    ]
    for symbol in symbols:
        if args.mode == "auto":
            evaluate_and_trade(
                client,
                config,
                symbol,
                args.order_type,
                args.limit_price,
                args.no_trade_reason,
                args.no_trade_context,
                args.no_trade_emotion,
                args.no_trade_notes,
            )
        else:
            evaluate_and_queue(
                client,
                config,
                symbol,
                args.order_type,
                args.limit_price,
                args.no_trade_reason,
                args.no_trade_context,
                args.no_trade_emotion,
                args.no_trade_notes,
            )


def handle_review_queue(config: AppConfig, args: argparse.Namespace) -> None:
    rows = list_review_queue(config.review_queue_path)
    if not rows:
        print("Review queue empty.")
        return
    for row in rows:
        print(
            "review_needed:"
            f" trade_id={row['trade_id']}"
            f" symbol={row['symbol']}"
            f" exit_ts={row['exit_ts']}"
            f" exit_price={row['exit_price']}"
        )


def handle_signal_queue(config: AppConfig, args: argparse.Namespace) -> None:
    rows = list_signal_queue(config.signal_queue_path, args.status)
    if not rows:
        print("No signals found.")
        return
    for row in rows:
        print(
            f"signal_id={row['signal_id']} status={row['status']} "
            f"{row['symbol']} {row['direction']} setup={row['setup_name']} "
            f"created={row['created_ts']}"
        )
        if args.verbose:
            print(
                "signal_details:"
                f" order_type={row.get('order_type')}"
                f" limit_price={row.get('limit_price')}"
                f" qty={row.get('qty')}"
            )
            print(f"entry_reason: {row.get('entry_reason')}")
            print(f"invalidation_reason: {row.get('invalidation_reason')}")
            print(f"stop_loss_logic: {row.get('stop_loss_logic')}")
            print(f"take_profit_logic: {row.get('take_profit_logic')}")
            print(f"market_context: {row.get('market_context')}")
            print(f"emotional_state: {row.get('emotional_state')}")


def handle_approve_signal(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    rows = list_signal_queue(config.signal_queue_path, status="pending")
    match = next((row for row in rows if row["signal_id"] == args.signal_id), None)
    if not match:
        raise RuntimeError("Signal not found or not pending.")
    order_type = match.get("order_type", "market")
    limit_price = match.get("limit_price") or None
    if limit_price is not None:
        limit_price = float(limit_price)
    qty = float(match.get("qty") or config.fixed_position_size)
    idea = {
        "symbol": match["symbol"],
        "direction": match["direction"],
        "setup_name": match["setup_name"],
        "entry_reason": match["entry_reason"],
        "invalidation_reason": match["invalidation_reason"],
        "stop_loss_logic": match["stop_loss_logic"],
        "take_profit_logic": match["take_profit_logic"],
        "market_context": match["market_context"],
        "emotional_state": match["emotional_state"],
    }
    order = client.place_order(
        symbol=idea["symbol"],
        side="buy" if idea["direction"] == "long" else "sell",
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
    )
    trade_id = log_entry(
        journal_path=config.journal_path,
        idea=idea,
        order=order,
    )
    update_signal_status(
        config.signal_queue_path,
        signal_id=args.signal_id,
        status="executed",
        decision_reason=args.reason or "approved",
    )
    print(f"Approved signal -> trade_id={trade_id}")


def handle_ignore_signal(config: AppConfig, args: argparse.Namespace) -> None:
    update_signal_status(
        config.signal_queue_path,
        signal_id=args.signal_id,
        status="ignored",
        decision_reason=args.reason or "ignored",
    )
    print(f"Ignored signal: signal_id={args.signal_id}")


def handle_close_position(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    trade_id = find_open_trade_id(config.journal_path, args.symbol)
    if not trade_id:
        print("No open trade found for symbol.")
        return
    order = client.close_position(args.symbol)
    order_id = str(order.id)
    deadline = time.time() + args.wait_seconds
    filled = None
    while time.time() < deadline:
        refreshed = client.get_order(order_id)
        if refreshed.filled_avg_price and refreshed.filled_at:
            filled = refreshed
            break
        time.sleep(1)
    if filled:
        log_exit(
            journal_path=config.journal_path,
            trade_id=trade_id,
            exit_ts=filled.filled_at.isoformat(),
            exit_price=float(filled.filled_avg_price),
            outcome=args.outcome,
            r_multiple=args.r_multiple,
            exit_reason=args.exit_reason,
            what_went_right=args.what_went_right,
            what_went_wrong=args.what_went_wrong,
            improvement_idea=args.improvement_idea,
            exit_order_id=order_id,
        )
        print(f"Closed and logged exit: trade_id={trade_id}")
        return

    add_pending_review(
        config.pending_reviews_path,
        trade_id=trade_id,
        outcome=args.outcome,
        r_multiple=args.r_multiple,
        exit_reason=args.exit_reason,
        what_went_right=args.what_went_right,
        what_went_wrong=args.what_went_wrong,
        improvement_idea=args.improvement_idea,
    )
    print(
        "Close submitted but not filled yet."
        f" Added pending review for trade_id={trade_id}"
    )


def handle_backtest(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    if args.recent_days:
        end = args.end or pd.Timestamp.now(tz="UTC").date().isoformat()
        start = (
            args.start
            or (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=args.recent_days * 3))
            .date()
            .isoformat()
        )
    else:
        start = args.start
        end = args.end
    if not args.recent_days and (not start or not end):
        raise RuntimeError("start and end are required unless --recent-days is used.")
    result = run_backtest(
        client=client,
        symbol=args.symbol,
        start=start or "",
        end=end or "",
        risk_multiple=args.risk_multiple,
        time_stop_days=args.time_stop_days,
        output_path=args.output,
        setup_name=args.setup,
        recent_days=args.recent_days,
        regime_filter=_regime_filter(config) if args.use_regime else None,
    )
    print(f"trades_path: {result.trades_path}")
    print(f"total_trades: {result.total_trades}")
    print(f"win_rate: {result.win_rate:.2f}")
    print(f"avg_r: {result.avg_r:.2f}")
    print(f"median_r: {result.median_r:.2f}")
    print(f"best_r: {result.best_r:.2f}")
    print(f"worst_r: {result.worst_r:.2f}")


def handle_backtest_summary(config: AppConfig, args: argparse.Namespace) -> None:
    summary = summarize_backtest(args.trades_path)
    yearly = summary["yearly"]
    monthly = summary["monthly"]
    if not yearly and not monthly:
        print("No trades to summarize.")
        return
    if yearly:
        print("yearly:")
        for row in yearly:
            print(
                f"  {row['year']}: trades={int(row['trades'])} "
                f"win_rate={row['win_rate']:.2f} avg_r={row['avg_r']:.2f}"
            )
    if monthly:
        print("monthly:")
        for row in monthly[-args.months:]:
            print(
                f"  {row['month']}: trades={int(row['trades'])} "
                f"win_rate={row['win_rate']:.2f} avg_r={row['avg_r']:.2f}"
            )


def handle_backtest_rollup(config: AppConfig, args: argparse.Namespace) -> None:
    if args.output:
        output_path = args.output
    else:
        today = date_cls.today().isoformat()
        output_path = f"knowledge/reviews/monthly_backtest_rollup_{today}.md"
    path = write_backtest_rollup(
        input_glob=args.glob,
        months=args.months,
        output_path=output_path,
    )
    print(f"wrote_rollup: {path}")


def handle_assess_signal(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    rows = list_signal_queue(config.signal_queue_path, status="pending")
    match = next((row for row in rows if row["signal_id"] == args.signal_id), None)
    if not match:
        raise RuntimeError("Signal not found or not pending.")
    setup_name = match["setup_name"]
    output_path = args.output or f"data/backtest_recent_{setup_name}.csv"
    result = run_recent_backtest(
        client=client,
        symbol=match["symbol"],
        recent_days=args.recent_days,
        risk_multiple=args.risk_multiple,
        time_stop_days=args.time_stop_days,
        output_path=output_path,
        setup_name=setup_name,
        regime_filter=_regime_filter(config) if args.use_regime else None,
    )
    print(f"setup_name: {setup_name}")
    print(f"recent_days: {args.recent_days}")
    print(f"trades_path: {result.trades_path}")
    print(f"total_trades: {result.total_trades}")
    print(f"win_rate: {result.win_rate:.2f}")
    print(f"avg_r: {result.avg_r:.2f}")
    print(f"median_r: {result.median_r:.2f}")
    print(f"best_r: {result.best_r:.2f}")
    print(f"worst_r: {result.worst_r:.2f}")


def _loss_streak(outcomes: list[str]) -> int:
    streak = 0
    for outcome in reversed(outcomes):
        if outcome != "loss":
            break
        streak += 1
    return streak


def _load_hot_only_state(path: str) -> dict[tuple[str, str], dict]:
    state: dict[tuple[str, str], dict] = {}
    if not os.path.exists(path):
        return state
    with open(path, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            symbol = row.get("symbol", "").upper()
            setup_name = row.get("setup_name", "")
            if not symbol or not setup_name:
                continue
            state[(symbol, setup_name)] = row
    return state


def _save_hot_only_state(path: str, state: dict[tuple[str, str], dict]) -> None:
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    fieldnames = [
        "symbol",
        "setup_name",
        "paused",
        "pause_reason",
        "paused_ts",
        "close_count_at_pause",
        "reactivated_ts",
        "updated_ts",
    ]
    rows = [state[key] for key in sorted(state.keys())]
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _closed_trade_outcomes(
    journal_path: str,
    symbol: str,
    setup_name: str,
) -> list[str]:
    rows = list(read_rows(journal_path))
    filtered = []
    for row in rows:
        if row.get("symbol", "").upper() != symbol.upper():
            continue
        if row.get("setup_name", "") != setup_name:
            continue
        outcome = row.get("outcome", "").strip()
        if not outcome:
            continue
        ts = row.get("exit_ts", "") or row.get("entry_ts", "")
        filtered.append((ts, outcome))
    filtered.sort(key=lambda value: value[0])
    return [value[1] for value in filtered]


def handle_assess_multi(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    rows = list_signal_queue(config.signal_queue_path, status="pending")
    match = next((row for row in rows if row["signal_id"] == args.signal_id), None)
    if not match:
        raise RuntimeError("Signal not found or not pending.")

    symbol = match["symbol"]
    setup_name = match["setup_name"]
    windows = [int(value) for value in args.windows.split(",") if value.strip()]
    if not windows:
        raise ValueError("No valid windows provided.")

    results: dict[int, BacktestResult] = {}
    for window in windows:
        output_path = os.path.join(
            args.output_dir,
            f"backtest_assess_{symbol}_{setup_name}_{window}d.csv",
        )
        result = run_recent_backtest(
            client=client,
            symbol=symbol,
            recent_days=window,
            risk_multiple=args.risk_multiple,
            time_stop_days=args.time_stop_days,
            output_path=output_path,
            setup_name=setup_name,
            regime_filter=_regime_filter(config) if args.use_regime else None,
        )
        results[window] = result

    def _metric(window: int, name: str, default: float = 0.0) -> float:
        result = results.get(window)
        if not result:
            return default
        return float(getattr(result, name))

    trades_30 = int(_metric(30, "total_trades", 0))
    trades_90 = int(_metric(90, "total_trades", 0))
    trades_180 = int(_metric(180, "total_trades", 0))
    avg_r_30 = _metric(30, "avg_r")
    avg_r_90 = _metric(90, "avg_r")
    avg_r_180 = _metric(180, "avg_r")
    median_r_180 = _metric(180, "median_r")

    avg_r_floor = max(args.avg_r_floor, 0.01)
    hot_ratio = avg_r_30 / max(avg_r_180, avg_r_floor)

    approve = (
        trades_90 >= args.min_trades_90
        and trades_180 >= args.min_trades_180
        and avg_r_180 >= args.min_avg_r_180
        and median_r_180 >= args.min_median_r_180
        and hot_ratio <= args.max_hot_ratio
    )

    hot_only = (
        trades_30 >= args.min_trades_30
        and avg_r_30 >= args.min_avg_r_30
        and (avg_r_90 < args.min_avg_r_90 or avg_r_180 < args.min_avg_r_180)
    )

    state_key = (symbol.upper(), setup_name)
    hot_state = _load_hot_only_state(args.state_path)
    state_row = hot_state.get(
        state_key,
        {
            "symbol": symbol.upper(),
            "setup_name": setup_name,
            "paused": "false",
            "pause_reason": "",
            "paused_ts": "",
            "close_count_at_pause": "0",
            "reactivated_ts": "",
            "updated_ts": "",
        },
    )

    executed_outcomes = _closed_trade_outcomes(config.journal_path, symbol, setup_name)
    executed_count = len(executed_outcomes)
    loss_streak = _loss_streak(executed_outcomes)
    recent_outcomes = executed_outcomes[-args.hot_pause_lookback :]
    recent_losses = sum(1 for value in recent_outcomes if value == "loss")

    is_paused = state_row.get("paused", "false").lower() == "true"
    close_count_at_pause = int(state_row.get("close_count_at_pause", "0") or "0")
    closed_since_pause = max(0, executed_count - close_count_at_pause)
    pause_reason = state_row.get("pause_reason", "")

    now_ts = datetime.now(timezone.utc).isoformat()
    if hot_only:
        hit_streak = loss_streak >= args.hot_kill_streak
        hit_window = recent_losses >= args.hot_pause_losses
        if (not is_paused) and (hit_streak or hit_window):
            is_paused = True
            close_count_at_pause = executed_count
            pause_reason = (
                f"paused: loss_streak={loss_streak} recent_losses="
                f"{recent_losses}/{args.hot_pause_lookback}"
            )
            state_row["paused_ts"] = now_ts

        if is_paused:
            can_reactivate = (
                closed_since_pause >= args.hot_reactivate_min_trades
                and trades_30 >= args.min_trades_30
                and avg_r_30 >= args.hot_reactivate_min_avg_r_30
            )
            if can_reactivate:
                is_paused = False
                pause_reason = "reactivated by 30d strength + new trade sample"
                state_row["reactivated_ts"] = now_ts
    elif approve:
        # If the setup graduates to stable approve, clear hot-only pause.
        is_paused = False
        pause_reason = "cleared by stable approve recommendation"

    if approve:
        recommendation = "approve"
    elif hot_only and not is_paused:
        recommendation = "hot-only"
    else:
        recommendation = "reject"

    state_row["paused"] = "true" if is_paused else "false"
    state_row["pause_reason"] = pause_reason
    state_row["close_count_at_pause"] = str(close_count_at_pause)
    state_row["updated_ts"] = now_ts
    hot_state[state_key] = state_row
    _save_hot_only_state(args.state_path, hot_state)

    today = date_cls.today().isoformat()
    output_path = args.output or (
        f"knowledge/reviews/assess_multi_{today}_{symbol}_{setup_name}.md"
    )
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    lines: list[str] = []
    lines.append(f"Assess multi ({today})")
    lines.append("")
    lines.append(f"signal_id: {match['signal_id']}")
    lines.append(f"symbol: {symbol}")
    lines.append(f"setup: {setup_name}")
    lines.append("")
    lines.append("windows:")
    for window in sorted(results.keys()):
        result = results[window]
        lines.append(
            f"- {window}d: trades={result.total_trades} "
            f"win_rate={result.win_rate:.2f} avg_r={result.avg_r:.2f} "
            f"median_r={result.median_r:.2f} best_r={result.best_r:.2f} "
            f"worst_r={result.worst_r:.2f} trades_path={result.trades_path}"
        )
    lines.append("")
    lines.append("thresholds:")
    lines.append(
        f"- min_trades_30={args.min_trades_30} min_trades_90={args.min_trades_90} "
        f"min_trades_180={args.min_trades_180}"
    )
    lines.append(
        f"- min_avg_r_30={args.min_avg_r_30:.2f} min_avg_r_90={args.min_avg_r_90:.2f} "
        f"min_avg_r_180={args.min_avg_r_180:.2f}"
    )
    lines.append(f"- min_median_r_180={args.min_median_r_180:.2f}")
    lines.append(f"- max_hot_ratio={args.max_hot_ratio:.2f} avg_r_floor={avg_r_floor:.2f}")
    lines.append("")
    lines.append("derived:")
    lines.append(f"- avg_r_30={avg_r_30:.2f} avg_r_90={avg_r_90:.2f} avg_r_180={avg_r_180:.2f}")
    lines.append(f"- median_r_180={median_r_180:.2f}")
    lines.append(f"- hot_ratio={hot_ratio:.2f}")
    lines.append(f"- executed_trades={executed_count}")
    lines.append(f"- executed_loss_streak={loss_streak}")
    lines.append(
        f"- recent_losses={recent_losses}/{args.hot_pause_lookback} "
        f"pause_threshold={args.hot_pause_losses}"
    )
    lines.append(f"- closed_since_pause={closed_since_pause}")
    lines.append(f"- hot_pause_streak={args.hot_kill_streak}")
    lines.append(f"- hot_state_path={args.state_path}")
    lines.append(f"- hot_paused={str(is_paused).lower()}")
    lines.append(f"- hot_pause_reason={pause_reason or 'none'}")
    lines.append("")
    lines.append(f"recommendation: {recommendation}")
    lines.append(f"hot_only_max_allocation: {args.hot_max_allocation:.0%}")
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")

    print(f"recommendation: {recommendation}")
    print(f"wrote_assess_multi: {output_path}")

def handle_review_snapshot(config: AppConfig, args: argparse.Namespace) -> None:
    path = write_weekly_snapshot(
        config.journal_path,
        config.no_trade_journal_path,
        args.date,
        args.output_dir,
    )
    print(f"wrote_snapshot: {path}")


def handle_no_trade_summary(config: AppConfig, args: argparse.Namespace) -> None:
    days = 1 if args.window == "daily" else 7
    summary = no_trade_summary(config.no_trade_journal_path, args.date, days)
    print(f"total_no_trades: {summary['total_no_trades']}")
    print(f"top_reason: {summary['top_reason']}")
    print(f"top_context: {summary['top_context']}")
    print(f"top_emotion: {summary['top_emotion']}")


def handle_backtest_batch(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    symbols = (
        [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
        if args.symbols
        else _read_universe(args.universe_path or config.universe_path)
    )
    setups = (
        [value.strip() for value in args.setups.split(",") if value.strip()]
        if args.setups
        else config.enabled_setups
    )
    windows = [int(value) for value in args.windows.split(",") if value.strip()]
    regime_filter = _regime_filter(config) if args.use_regime else None

    for symbol in symbols:
        for setup in setups:
            for window in windows:
                output = f"{args.output_dir}/backtest_{symbol}_{setup}_{window}d.csv"
                end = pd.Timestamp.now(tz="UTC").date().isoformat()
                start = (
                    pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=window * 3)
                ).date().isoformat()
                result = run_backtest(
                    client=client,
                    symbol=symbol,
                    start=start,
                    end=end,
                    risk_multiple=args.risk_multiple,
                    time_stop_days=args.time_stop_days,
                    output_path=output,
                    setup_name=setup,
                    recent_days=window,
                    regime_filter=regime_filter,
                )
                print(
                    f"{symbol} {setup} {window}d "
                    f"trades={result.total_trades} win_rate={result.win_rate:.2f} "
                    f"avg_r={result.avg_r:.2f}"
                )


def handle_scan(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    symbols = (
        [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
        if args.symbols
        else _read_universe(args.universe_path or config.universe_path)
    )
    regime_filter = _regime_filter(config)
    ideas: list[dict] = []
    for symbol in symbols:
        if symbol in config.watch_only_symbols and not args.include_watch_only:
            continue
        allowed_setups = _allowed_setups_for_symbol(config, symbol)
        idea = find_trade_idea(
            client,
            symbol,
            allowed_setups,
            regime_filter=regime_filter,
        )
        if idea:
            ideas.append(idea)

    if args.output:
        output_path = args.output
    else:
        today = date_cls.today().isoformat()
        output_path = f"knowledge/reviews/scan_{today}.md"

    lines = []
    lines.append(f"Daily scan ({date_cls.today().isoformat()})")
    lines.append("")
    lines.append(f"symbols_scanned: {len(symbols)}")
    lines.append(f"candidates: {len(ideas)}")
    lines.append(
        f"regime_filter: {'on' if regime_filter.get('enabled') else 'off'} "
        f"(fast={regime_filter.get('fast_sma')}, slow={regime_filter.get('slow_sma')})"
    )
    lines.append("")
    lines.append("| symbol | setup | direction | entry_reason | stop | target |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for idea in ideas:
        lines.append(
            f"| {idea['symbol']} | {idea['setup_name']} | {idea['direction']} | "
            f"{idea['entry_reason']} | {idea['stop_loss_logic']} | {idea['take_profit_logic']} |"
        )

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    print(f"wrote_scan: {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V0 paper-trading system")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trade_parser = subparsers.add_parser("trade", help="Evaluate and place a trade")
    trade_parser.add_argument("--symbol", required=True, help="Symbol to evaluate")
    trade_parser.add_argument(
        "--order-type",
        choices=["market", "limit"],
        default="market",
        help="Order type",
    )
    trade_parser.add_argument(
        "--limit-price",
        type=float,
        default=None,
        help="Limit price (required for limit orders)",
    )
    trade_parser.add_argument(
        "--no-trade-reason",
        default="No valid setup",
        help="Reason logged when no trade is taken",
    )
    trade_parser.add_argument(
        "--no-trade-context",
        default="unclear",
        help="Market context logged when no trade is taken",
    )
    trade_parser.add_argument(
        "--no-trade-emotion",
        default="calm",
        help="Emotional state logged when no trade is taken",
    )
    trade_parser.add_argument(
        "--no-trade-notes",
        default="",
        help="Optional notes logged when no trade is taken",
    )

    signal_parser = subparsers.add_parser(
        "signal", help="Evaluate and queue a signal (no trade)"
    )
    signal_parser.add_argument("--symbol", required=True, help="Symbol to evaluate")
    signal_parser.add_argument(
        "--order-type",
        choices=["market", "limit"],
        default="market",
        help="Order type",
    )
    signal_parser.add_argument(
        "--limit-price",
        type=float,
        default=None,
        help="Limit price (required for limit orders)",
    )
    signal_parser.add_argument(
        "--no-trade-reason",
        default="No valid setup",
        help="Reason logged when no trade is taken",
    )
    signal_parser.add_argument(
        "--no-trade-context",
        default="unclear",
        help="Market context logged when no trade is taken",
    )
    signal_parser.add_argument(
        "--no-trade-emotion",
        default="calm",
        help="Emotional state logged when no trade is taken",
    )
    signal_parser.add_argument(
        "--no-trade-notes",
        default="",
        help="Optional notes logged when no trade is taken",
    )

    exit_parser = subparsers.add_parser("log-exit", help="Log trade exit + review")
    exit_parser.add_argument("--trade-id", required=True, help="Trade ID to update")
    exit_parser.add_argument("--exit-price", type=float, required=True, help="Exit price")
    exit_parser.add_argument(
        "--exit-ts",
        default=None,
        help="Exit timestamp (ISO). Defaults to now.",
    )
    exit_parser.add_argument(
        "--outcome",
        choices=["win", "loss", "scratch"],
        required=True,
        help="Trade outcome",
    )
    exit_parser.add_argument("--r-multiple", type=float, required=True, help="R multiple")
    exit_parser.add_argument("--exit-reason", required=True, help="Exit reason")
    exit_parser.add_argument("--what-went-right", required=True, help="What went right")
    exit_parser.add_argument("--what-went-wrong", required=True, help="What went wrong")
    exit_parser.add_argument(
        "--improvement-idea",
        required=True,
        help="One concrete improvement idea",
    )

    review_parser = subparsers.add_parser("review", help="Review trades")
    review_parser.add_argument(
        "--window",
        choices=["daily", "weekly"],
        default="daily",
        help="Review window",
    )
    review_parser.add_argument(
        "--date",
        default=None,
        help="Anchor date (YYYY-MM-DD). Defaults to today.",
    )

    review_queue_parser = subparsers.add_parser(
        "review-queue", help="List trades that need post-trade review"
    )

    daily_report_parser = subparsers.add_parser(
        "daily-report", help="Write a daily markdown report"
    )
    daily_report_parser.add_argument(
        "--date",
        default=None,
        help="Anchor date (YYYY-MM-DD or ISO datetime). Defaults to today.",
    )
    daily_report_parser.add_argument(
        "--output-dir",
        default="knowledge/reviews",
        help="Directory for daily report files",
    )

    sync_parser = subparsers.add_parser("sync", help="Sync entry prices from Alpaca")
    sync_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of recent closed orders to scan",
    )

    run_parser = subparsers.add_parser("run-daily", help="Run once after market close")
    run_parser.add_argument("--symbol", required=True, help="Symbol to evaluate")
    run_parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated list of symbols to evaluate",
    )
    run_parser.add_argument(
        "--mode",
        choices=["propose", "auto"],
        default="propose",
        help="Propose a signal (semi-auto) or auto-place trades",
    )
    run_parser.add_argument(
        "--order-type",
        choices=["market", "limit"],
        default="market",
        help="Order type",
    )
    run_parser.add_argument(
        "--limit-price",
        type=float,
        default=None,
        help="Limit price (required for limit orders)",
    )
    run_parser.add_argument(
        "--buffer-minutes",
        type=int,
        default=20,
        help="Minutes after market close to run",
    )
    run_parser.add_argument(
        "--weekly-snapshot",
        action="store_true",
        help="Write weekly review snapshot on the configured weekday",
    )
    run_parser.add_argument(
        "--weekly-snapshot-day",
        type=int,
        default=4,
        help="Weekday for snapshot (0=Mon ... 4=Fri)",
    )
    run_parser.add_argument(
        "--weekly-snapshot-dir",
        default="knowledge/reviews",
        help="Directory for weekly snapshot files",
    )
    run_parser.add_argument(
        "--sync-limit",
        type=int,
        default=200,
        help="Number of recent closed orders to scan for sync",
    )
    run_parser.add_argument(
        "--no-trade-reason",
        default="No valid setup",
        help="Reason logged when no trade is taken",
    )
    run_parser.add_argument(
        "--no-trade-context",
        default="unclear",
        help="Market context logged when no trade is taken",
    )
    run_parser.add_argument(
        "--no-trade-emotion",
        default="calm",
        help="Emotional state logged when no trade is taken",
    )
    run_parser.add_argument(
        "--no-trade-notes",
        default="",
        help="Optional notes logged when no trade is taken",
    )

    run_once_parser = subparsers.add_parser(
        "run-once", help="Run the evaluation immediately for one or more symbols"
    )
    run_once_parser.add_argument("--symbol", required=True, help="Symbol to evaluate")
    run_once_parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated list of symbols to evaluate",
    )
    run_once_parser.add_argument(
        "--mode",
        choices=["propose", "auto"],
        default="propose",
        help="Propose a signal (semi-auto) or auto-place trades",
    )
    run_once_parser.add_argument(
        "--order-type",
        choices=["market", "limit"],
        default="market",
        help="Order type",
    )
    run_once_parser.add_argument(
        "--limit-price",
        type=float,
        default=None,
        help="Limit price (required for limit orders)",
    )
    run_once_parser.add_argument(
        "--no-trade-reason",
        default="No valid setup",
        help="Reason logged when no trade is taken",
    )
    run_once_parser.add_argument(
        "--no-trade-context",
        default="unclear",
        help="Market context logged when no trade is taken",
    )
    run_once_parser.add_argument(
        "--no-trade-emotion",
        default="calm",
        help="Emotional state logged when no trade is taken",
    )
    run_once_parser.add_argument(
        "--no-trade-notes",
        default="",
        help="Optional notes logged when no trade is taken",
    )

    run_sync_parser = subparsers.add_parser(
        "run-sync", help="Continuously sync exit fields from Alpaca"
    )
    run_sync_parser.add_argument(
        "--interval-minutes",
        type=int,
        default=5,
        help="Minutes between sync runs",
    )
    run_sync_parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Number of recent closed orders to scan",
    )

    close_parser = subparsers.add_parser(
        "close-position", help="Close a position and log review in one step"
    )
    close_parser.add_argument("--symbol", required=True, help="Symbol to close")
    close_parser.add_argument(
        "--wait-seconds",
        type=int,
        default=10,
        help="Seconds to wait for fill before deferring review",
    )
    close_parser.add_argument(
        "--outcome",
        choices=["win", "loss", "scratch"],
        required=True,
        help="Trade outcome",
    )
    close_parser.add_argument("--r-multiple", type=float, required=True, help="R multiple")
    close_parser.add_argument("--exit-reason", required=True, help="Exit reason")
    close_parser.add_argument("--what-went-right", required=True, help="What went right")
    close_parser.add_argument("--what-went-wrong", required=True, help="What went wrong")
    close_parser.add_argument(
        "--improvement-idea",
        required=True,
        help="One concrete improvement idea",
    )

    signal_queue_parser = subparsers.add_parser(
        "signal-queue", help="List queued trade signals"
    )
    signal_queue_parser.add_argument(
        "--status",
        choices=["pending", "executed", "ignored"],
        default="pending",
        help="Filter by status",
    )
    signal_queue_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full signal details",
    )

    approve_signal_parser = subparsers.add_parser(
        "approve-signal", help="Approve and place a queued signal"
    )
    approve_signal_parser.add_argument("--signal-id", required=True, help="Signal ID")
    approve_signal_parser.add_argument(
        "--reason",
        default="",
        help="Why this signal was approved",
    )

    ignore_signal_parser = subparsers.add_parser(
        "ignore-signal", help="Ignore a queued signal"
    )
    ignore_signal_parser.add_argument("--signal-id", required=True, help="Signal ID")
    ignore_signal_parser.add_argument(
        "--reason",
        default="",
        help="Why this signal was ignored",
    )

    backtest_parser = subparsers.add_parser(
        "backtest", help="Run a simple daily-bar backtest"
    )
    backtest_parser.add_argument("--symbol", required=True, help="Symbol to test")
    backtest_parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    backtest_parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    backtest_parser.add_argument(
        "--risk-multiple",
        type=float,
        default=2.0,
        help="Take profit multiple (R)",
    )
    backtest_parser.add_argument(
        "--time-stop-days",
        type=int,
        default=5,
        help="Max holding days before time stop",
    )
    backtest_parser.add_argument(
        "--setup",
        choices=["PrevDayBreakout_D1", "MeanReversion_D1", "TwoDayBreakout_D1"],
        default="PrevDayBreakout_D1",
        help="Setup to backtest",
    )
    backtest_parser.add_argument(
        "--recent-days",
        type=int,
        default=None,
        help="Limit to most recent N trading days",
    )
    backtest_parser.add_argument(
        "--output",
        default="data/backtest_trades.csv",
        help="CSV output path",
    )
    backtest_parser.add_argument(
        "--use-regime",
        action="store_true",
        help="Apply regime filter to backtest signals",
    )

    backtest_summary_parser = subparsers.add_parser(
        "backtest-summary", help="Summarize backtest trades by year and month"
    )
    backtest_summary_parser.add_argument(
        "--trades-path",
        default="data/backtest_trades.csv",
        help="Backtest trades CSV path",
    )
    backtest_summary_parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Number of recent months to show",
    )

    backtest_rollup_parser = subparsers.add_parser(
        "backtest-rollup", help="Write a monthly rollup across backtest CSVs"
    )
    backtest_rollup_parser.add_argument(
        "--glob",
        default="data/backtest_*_90d.csv",
        help="Glob for backtest CSVs to include",
    )
    backtest_rollup_parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Number of recent months to include",
    )
    backtest_rollup_parser.add_argument(
        "--output",
        default=None,
        help="Markdown output path (defaults to knowledge/reviews/...)",
    )

    review_snapshot_parser = subparsers.add_parser(
        "review-snapshot", help="Write a weekly review snapshot to the knowledge base"
    )
    review_snapshot_parser.add_argument(
        "--date",
        default=None,
        help="Anchor date (YYYY-MM-DD). Defaults to today.",
    )
    review_snapshot_parser.add_argument(
        "--output-dir",
        default="knowledge/reviews",
        help="Directory for snapshot files",
    )

    assess_signal_parser = subparsers.add_parser(
        "assess-signal", help="Backtest recent window for a queued signal"
    )
    assess_signal_parser.add_argument("--signal-id", required=True, help="Signal ID")
    assess_signal_parser.add_argument(
        "--recent-days",
        type=int,
        default=60,
        help="Recent trading days to assess",
    )
    assess_signal_parser.add_argument(
        "--risk-multiple",
        type=float,
        default=2.0,
        help="Take profit multiple (R)",
    )
    assess_signal_parser.add_argument(
        "--time-stop-days",
        type=int,
        default=5,
        help="Max holding days before time stop",
    )
    assess_signal_parser.add_argument(
        "--output",
        default=None,
        help="CSV output path (optional)",
    )
    assess_signal_parser.add_argument(
        "--use-regime",
        action="store_true",
        help="Apply regime filter to assessment backtest",
    )

    assess_multi_parser = subparsers.add_parser(
        "assess-multi",
        help="Assess a queued signal across multiple windows with a recommendation",
    )
    assess_multi_parser.add_argument("--signal-id", required=True, help="Signal ID")
    assess_multi_parser.add_argument(
        "--windows",
        default="30,90,180",
        help="Comma-separated recent trading days to assess",
    )
    assess_multi_parser.add_argument(
        "--risk-multiple",
        type=float,
        default=2.0,
        help="Take profit multiple (R)",
    )
    assess_multi_parser.add_argument(
        "--time-stop-days",
        type=int,
        default=5,
        help="Max holding days before time stop",
    )
    assess_multi_parser.add_argument(
        "--output-dir",
        default="data",
        help="Directory for assessment CSV outputs",
    )
    assess_multi_parser.add_argument(
        "--output",
        default=None,
        help="Markdown output path (optional)",
    )
    assess_multi_parser.add_argument(
        "--use-regime",
        action="store_true",
        help="Apply regime filter to assessment backtests",
    )
    assess_multi_parser.add_argument(
        "--min-trades-30",
        type=int,
        default=5,
        help="Minimum trades in 30d window for hot-only",
    )
    assess_multi_parser.add_argument(
        "--min-trades-90",
        type=int,
        default=8,
        help="Minimum trades in 90d window to approve",
    )
    assess_multi_parser.add_argument(
        "--min-trades-180",
        type=int,
        default=20,
        help="Minimum trades in 180d window to approve",
    )
    assess_multi_parser.add_argument(
        "--min-avg-r-30",
        type=float,
        default=0.30,
        help="Minimum avg R in 30d window for hot-only",
    )
    assess_multi_parser.add_argument(
        "--min-avg-r-90",
        type=float,
        default=0.10,
        help="Minimum avg R in 90d window",
    )
    assess_multi_parser.add_argument(
        "--min-avg-r-180",
        type=float,
        default=0.10,
        help="Minimum avg R in 180d window to approve",
    )
    assess_multi_parser.add_argument(
        "--min-median-r-180",
        type=float,
        default=0.0,
        help="Minimum median R in 180d window to approve",
    )
    assess_multi_parser.add_argument(
        "--max-hot-ratio",
        type=float,
        default=2.0,
        help="Maximum avg_r_30 / avg_r_180 ratio before flagging fading",
    )
    assess_multi_parser.add_argument(
        "--avg-r-floor",
        type=float,
        default=0.05,
        help="Floor for avg_r_180 in hot ratio calculation",
    )
    assess_multi_parser.add_argument(
        "--hot-kill-streak",
        type=int,
        default=2,
        help="Consecutive losses to trigger hot-only pause",
    )
    assess_multi_parser.add_argument(
        "--hot-pause-losses",
        type=int,
        default=3,
        help="Losses in the recent lookback to trigger hot-only pause",
    )
    assess_multi_parser.add_argument(
        "--hot-pause-lookback",
        type=int,
        default=4,
        help="Recent trade count used by hot-only loss window",
    )
    assess_multi_parser.add_argument(
        "--hot-reactivate-min-trades",
        type=int,
        default=6,
        help="Closed trades after pause required before hot-only reactivation",
    )
    assess_multi_parser.add_argument(
        "--hot-reactivate-min-avg-r-30",
        type=float,
        default=0.30,
        help="Minimum 30d avg R required for hot-only reactivation",
    )
    assess_multi_parser.add_argument(
        "--state-path",
        default="data/hot_only_state.csv",
        help="Path for persisted hot-only pause/reactivation state",
    )
    assess_multi_parser.add_argument(
        "--hot-max-allocation",
        type=float,
        default=0.2,
        help="Max allocation for hot-only signals (for reporting)",
    )

    backtest_batch_parser = subparsers.add_parser(
        "backtest-batch", help="Run backtests across a universe"
    )
    backtest_batch_parser.add_argument(
        "--universe-path",
        default=None,
        help="Universe file path (defaults to config)",
    )
    backtest_batch_parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols (overrides universe file)",
    )
    backtest_batch_parser.add_argument(
        "--setups",
        default=None,
        help="Comma-separated setups (defaults to enabled_setups)",
    )
    backtest_batch_parser.add_argument(
        "--windows",
        default="30,60,90",
        help="Comma-separated recent-day windows",
    )
    backtest_batch_parser.add_argument(
        "--risk-multiple",
        type=float,
        default=2.0,
        help="Take profit multiple (R)",
    )
    backtest_batch_parser.add_argument(
        "--time-stop-days",
        type=int,
        default=5,
        help="Max holding days before time stop",
    )
    backtest_batch_parser.add_argument(
        "--output-dir",
        default="data",
        help="Directory to write backtest CSVs",
    )
    backtest_batch_parser.add_argument(
        "--use-regime",
        action="store_true",
        help="Apply regime filter to batch backtests",
    )

    scan_parser = subparsers.add_parser(
        "scan", help="Scan universe and write a daily candidate list"
    )
    scan_parser.add_argument(
        "--universe-path",
        default=None,
        help="Universe file path (defaults to config)",
    )
    scan_parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols (overrides universe file)",
    )
    scan_parser.add_argument(
        "--output",
        default=None,
        help="Markdown output path (defaults to knowledge/reviews/scan_YYYY-MM-DD.md)",
    )
    scan_parser.add_argument(
        "--include-watch-only",
        action="store_true",
        help="Include watch-only symbols in scan",
    )

    no_trade_parser = subparsers.add_parser(
        "no-trade-summary", help="Summarize no-trade logs"
    )
    no_trade_parser.add_argument(
        "--window",
        choices=["daily", "weekly"],
        default="daily",
        help="Summary window",
    )
    no_trade_parser.add_argument(
        "--date",
        default=None,
        help="Anchor date (YYYY-MM-DD). Defaults to today.",
    )

    return parser


def main() -> None:
    config = AppConfig.from_env()
    init_journal(config.journal_path)
    init_no_trade_journal(config.no_trade_journal_path)
    init_pending_reviews(config.pending_reviews_path)
    init_review_queue(config.review_queue_path)
    init_signal_queue(config.signal_queue_path)

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "trade":
        handle_trade(config, args)
    elif args.command == "signal":
        handle_signal(config, args)
    elif args.command == "log-exit":
        handle_log_exit(config, args)
    elif args.command == "review":
        handle_review(config, args)
    elif args.command == "sync":
        handle_sync(config, args)
    elif args.command == "run-daily":
        handle_run_daily(config, args)
    elif args.command == "run-once":
        handle_run_once(config, args)
    elif args.command == "run-sync":
        handle_run_sync(config, args)
    elif args.command == "review-queue":
        handle_review_queue(config, args)
    elif args.command == "daily-report":
        handle_daily_report(config, args)
    elif args.command == "signal-queue":
        handle_signal_queue(config, args)
    elif args.command == "approve-signal":
        handle_approve_signal(config, args)
    elif args.command == "ignore-signal":
        handle_ignore_signal(config, args)
    elif args.command == "close-position":
        handle_close_position(config, args)
    elif args.command == "backtest":
        handle_backtest(config, args)
    elif args.command == "backtest-summary":
        handle_backtest_summary(config, args)
    elif args.command == "backtest-rollup":
        handle_backtest_rollup(config, args)
    elif args.command == "backtest-batch":
        handle_backtest_batch(config, args)
    elif args.command == "review-snapshot":
        handle_review_snapshot(config, args)
    elif args.command == "no-trade-summary":
        handle_no_trade_summary(config, args)
    elif args.command == "assess-signal":
        handle_assess_signal(config, args)
    elif args.command == "assess-multi":
        handle_assess_multi(config, args)
    elif args.command == "scan":
        handle_scan(config, args)


if __name__ == "__main__":
    main()
