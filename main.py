import argparse
import time
from datetime import datetime, timedelta, timezone
from datetime import date as date_cls

import pandas as pd

from alpaca_client import AlpacaClient
from backtest import run_backtest, summarize_backtest, run_recent_backtest
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
        return enabled
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
    idea = find_trade_idea(client, symbol, allowed_setups)
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
    idea = find_trade_idea(client, symbol, allowed_setups)
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
    qty = int(match.get("qty") or config.fixed_position_size)
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
    if summary["reason_counts"]:
        print("reason_counts:")
        for reason, count in summary["reason_counts"]:
            print(f"  {reason}: {count}")


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
        choices=["PrevDayBreakout_D1", "MeanReversion_D1"],
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
    elif args.command == "review-snapshot":
        handle_review_snapshot(config, args)
    elif args.command == "no-trade-summary":
        handle_no_trade_summary(config, args)
    elif args.command == "assess-signal":
        handle_assess_signal(config, args)


if __name__ == "__main__":
    main()
