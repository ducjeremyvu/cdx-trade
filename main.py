import argparse
import csv
import os
import re
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


def _latest_close_price(client: AlpacaClient, symbol: str) -> float:
    bars = client.get_recent_daily_bars(symbol, days=5)
    if bars is None or bars.empty:
        raise RuntimeError(f"No recent bars available for {symbol}")
    df = bars.reset_index()
    df = df.sort_values("timestamp")
    return float(df.iloc[-1]["close"])


def _open_exposure_usd(client: AlpacaClient) -> float:
    total = 0.0
    for position in client.list_open_positions():
        market_value = getattr(position, "market_value", None)
        if market_value not in (None, ""):
            total += abs(float(market_value))
            continue
        qty = float(getattr(position, "qty", 0) or 0)
        current_price = float(getattr(position, "current_price", 0) or 0)
        total += abs(qty * current_price)
    return total


def _capital_guard(
    client: AlpacaClient,
    config: AppConfig,
    symbol: str,
    qty: float,
    order_type: str,
    limit_price: float | None,
) -> tuple[bool, str]:
    if config.max_capital_usd <= 0:
        return True, ""
    if qty <= 0:
        return False, f"qty must be > 0, got {qty}"
    order_price = (
        float(limit_price)
        if order_type == "limit" and limit_price is not None
        else _latest_close_price(client, symbol)
    )
    order_notional = abs(qty * order_price)
    open_exposure = _open_exposure_usd(client)
    projected = open_exposure + order_notional
    if projected > config.max_capital_usd:
        return (
            False,
            (
                f"projected exposure ${projected:.2f} exceeds cap "
                f"${config.max_capital_usd:.2f} "
                f"(open=${open_exposure:.2f}, new=${order_notional:.2f})"
            ),
        )
    return True, (
        f"within cap: projected=${projected:.2f} "
        f"(open=${open_exposure:.2f}, new=${order_notional:.2f}, "
        f"cap=${config.max_capital_usd:.2f})"
    )


def _extract_stop_price(stop_loss_logic: str) -> float | None:
    if not stop_loss_logic:
        return None
    match = re.search(r"\(([-+]?[0-9]*\.?[0-9]+)\)", stop_loss_logic)
    if not match:
        return None
    return float(match.group(1))


def _open_position_map(client: AlpacaClient) -> dict[str, dict]:
    positions = {}
    for position in client.list_open_positions():
        symbol = getattr(position, "symbol", "").upper()
        if not symbol:
            continue
        qty = abs(float(getattr(position, "qty", 0) or 0))
        avg_entry_price = float(getattr(position, "avg_entry_price", 0) or 0)
        positions[symbol] = {
            "qty": qty,
            "avg_entry_price": avg_entry_price,
        }
    return positions


def _open_risk_to_stops_usd(client: AlpacaClient, journal_path: str) -> float:
    rows = list(read_rows(journal_path))
    open_rows = [row for row in rows if not row.get("exit_ts")]
    positions = _open_position_map(client)
    total_risk = 0.0
    for row in open_rows:
        symbol = row.get("symbol", "").upper()
        direction = row.get("direction", "long")
        stop_price = _extract_stop_price(row.get("stop_loss_logic", ""))
        position = positions.get(symbol)
        if not position or stop_price is None:
            continue
        entry_price = position["avg_entry_price"]
        qty = position["qty"]
        if direction == "long":
            risk = max(0.0, entry_price - stop_price) * qty
        else:
            risk = max(0.0, stop_price - entry_price) * qty
        total_risk += risk
    return total_risk


def _estimate_entry_price(
    client: AlpacaClient,
    symbol: str,
    order_type: str,
    limit_price: float | None,
) -> float:
    if order_type == "limit" and limit_price is not None:
        return float(limit_price)
    return _latest_close_price(client, symbol)


def _risk_guard(
    client: AlpacaClient,
    config: AppConfig,
    symbol: str,
    direction: str,
    stop_loss_logic: str,
    qty: float,
    order_type: str,
    limit_price: float | None,
) -> tuple[bool, str]:
    if config.max_total_open_risk_usd <= 0:
        return True, ""
    if qty <= 0:
        return False, f"qty must be > 0, got {qty}"
    stop_price = _extract_stop_price(stop_loss_logic)
    if stop_price is None:
        return False, "could not parse stop price from stop_loss_logic"
    entry_price = _estimate_entry_price(client, symbol, order_type, limit_price)
    if direction == "long":
        risk_per_unit = max(0.0, entry_price - stop_price)
    else:
        risk_per_unit = max(0.0, stop_price - entry_price)
    new_order_risk = risk_per_unit * abs(qty)
    open_risk = _open_risk_to_stops_usd(client, config.journal_path)
    projected_risk = open_risk + new_order_risk
    if projected_risk > config.max_total_open_risk_usd:
        return (
            False,
            (
                f"projected risk ${projected_risk:.2f} exceeds cap "
                f"${config.max_total_open_risk_usd:.2f} "
                f"(open=${open_risk:.2f}, new=${new_order_risk:.2f})"
            ),
        )
    return True, (
        f"within risk cap: projected=${projected_risk:.2f} "
        f"(open=${open_risk:.2f}, new=${new_order_risk:.2f}, "
        f"cap=${config.max_total_open_risk_usd:.2f})"
    )


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

    cap_allowed, cap_message = _capital_guard(
        client=client,
        config=config,
        symbol=idea["symbol"],
        qty=float(config.fixed_position_size),
        order_type=order_type,
        limit_price=limit_price,
    )
    if not cap_allowed:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Capital cap exceeded",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=cap_message,
        )
        print(f"Capital cap exceeded. Logged no-trade: log_id={log_id}")
        return None
    risk_allowed, risk_message = _risk_guard(
        client=client,
        config=config,
        symbol=idea["symbol"],
        direction=idea["direction"],
        stop_loss_logic=idea["stop_loss_logic"],
        qty=float(config.fixed_position_size),
        order_type=order_type,
        limit_price=limit_price,
    )
    if not risk_allowed:
        log_id = log_no_trade(
            config.no_trade_journal_path,
            symbol=symbol,
            reason="Risk cap exceeded",
            market_context=no_trade_context,
            emotional_state=no_trade_emotion,
            notes=risk_message,
        )
        print(f"Risk cap exceeded. Logged no-trade: log_id={log_id}")
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
    cap_allowed, cap_message = _capital_guard(
        client=client,
        config=config,
        symbol=match["symbol"],
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
    )
    if not cap_allowed:
        update_signal_status(
            config.signal_queue_path,
            signal_id=args.signal_id,
            status="ignored",
            decision_reason=cap_message,
        )
        print(
            f"Signal ignored due to capital cap: signal_id={args.signal_id} "
            f"reason={cap_message}"
        )
        return
    risk_allowed, risk_message = _risk_guard(
        client=client,
        config=config,
        symbol=match["symbol"],
        direction=match["direction"],
        stop_loss_logic=match["stop_loss_logic"],
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
    )
    if not risk_allowed:
        update_signal_status(
            config.signal_queue_path,
            signal_id=args.signal_id,
            status="ignored",
            decision_reason=risk_message,
        )
        print(
            f"Signal ignored due to risk cap: signal_id={args.signal_id} "
            f"reason={risk_message}"
        )
        return
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


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _closed_trade_rows(journal_path: str, window_days: int | None = None) -> list[dict]:
    rows = list(read_rows(journal_path))
    closed_rows = [row for row in rows if row.get("exit_ts")]
    if not window_days or window_days <= 0:
        return closed_rows
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=window_days)
    filtered = []
    for row in closed_rows:
        ts = pd.to_datetime(row.get("exit_ts"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        if ts >= cutoff:
            filtered.append(row)
    return filtered


def _closed_trade_r_values(journal_path: str, window_days: int | None = None) -> list[float]:
    rows = _closed_trade_rows(journal_path, window_days=window_days)
    values: list[float] = []
    for row in rows:
        parsed = _to_float(row.get("r_multiple"))
        if parsed is not None:
            values.append(parsed)
    return values


def _economics_metrics(
    config: AppConfig,
    monthly_ai_cost_usd: float | None,
    monthly_ops_cost_usd: float | None,
    target_net_usd: float | None,
    projected_monthly_gross_usd: float | None,
    auto_project: bool,
    projection_window_days: int | None,
    risk_per_trade_usd: float | None,
) -> dict:
    monthly_ai_cost = (
        monthly_ai_cost_usd
        if monthly_ai_cost_usd is not None
        else config.monthly_ai_cost_usd
    )
    monthly_ops_cost = (
        monthly_ops_cost_usd
        if monthly_ops_cost_usd is not None
        else config.monthly_ops_cost_usd
    )
    target_net = target_net_usd if target_net_usd is not None else config.target_net_usd
    window_days = (
        projection_window_days
        if projection_window_days is not None
        else config.economics_projection_window_days
    )
    risk_per_trade = (
        risk_per_trade_usd
        if risk_per_trade_usd is not None
        else config.economics_risk_per_trade_usd
    )
    window_r = _closed_trade_r_values(config.journal_path, window_days=window_days)
    window_avg_r = (sum(window_r) / len(window_r)) if window_r else 0.0
    window_trades_per_month = (
        (len(window_r) / max(1, window_days)) * 30 if window_days > 0 else 0.0
    )
    auto_projected_gross = window_avg_r * window_trades_per_month * risk_per_trade
    if auto_project and len(window_r) > 0:
        projected_gross = auto_projected_gross
        projection_mode = "auto_from_closed_trades"
    else:
        projected_gross = (
            projected_monthly_gross_usd
            if projected_monthly_gross_usd is not None
            else config.projected_monthly_gross_usd
        )
        projection_mode = "manual_config"
    monthly_total_cost = monthly_ai_cost + monthly_ops_cost
    projected_net = projected_gross - monthly_total_cost
    required_gross_for_target = monthly_total_cost + target_net
    return {
        "economic_ready": projected_net >= target_net,
        "monthly_ai_cost_usd": monthly_ai_cost,
        "monthly_ops_cost_usd": monthly_ops_cost,
        "monthly_total_cost_usd": monthly_total_cost,
        "projected_monthly_gross_usd": projected_gross,
        "projected_monthly_net_usd": projected_net,
        "target_net_usd": target_net,
        "required_gross_for_target_usd": required_gross_for_target,
        "projection_mode": projection_mode,
        "projection_window_days": window_days,
        "projection_risk_per_trade_usd": risk_per_trade,
        "window_closed_trades": len(window_r),
        "window_avg_r": window_avg_r,
        "window_trades_per_month": window_trades_per_month,
    }


def _go_live_metrics(
    config: AppConfig,
    min_trades: int,
    min_avg_r: float,
    max_drawdown_r_limit: float,
    require_no_pending_signals: bool,
    require_economic_ready: bool,
    economic_target_net_usd: float | None,
    economics_auto_project: bool,
    economics_projection_window_days: int | None,
    economics_risk_per_trade_usd: float | None,
    economics_projected_monthly_gross_usd: float | None,
) -> dict:
    r_values = _closed_trade_r_values(config.journal_path)
    avg_r = (sum(r_values) / len(r_values)) if r_values else 0.0
    trades = len(r_values)
    running = 0.0
    peak = 0.0
    max_drawdown_r = 0.0
    for value in r_values:
        running += value
        peak = max(peak, running)
        drawdown = running - peak
        max_drawdown_r = min(max_drawdown_r, drawdown)
    pending_reviews = len(list_review_queue(config.review_queue_path))
    pending_signals = len(list_signal_queue(config.signal_queue_path, status="pending"))
    checks = [
        ("min_trades", trades >= min_trades, f"trades={trades} threshold={min_trades}"),
        ("avg_r", avg_r >= min_avg_r, f"avg_r={avg_r:.2f} threshold={min_avg_r:.2f}"),
        (
            "max_drawdown_r",
            max_drawdown_r >= -max_drawdown_r_limit,
            f"max_drawdown_r={max_drawdown_r:.2f} limit=-{max_drawdown_r_limit:.2f}",
        ),
        ("pending_reviews", pending_reviews == 0, f"pending_reviews={pending_reviews}"),
        (
            "capital_cap_enabled",
            config.max_capital_usd > 0,
            f"max_capital_usd={config.max_capital_usd:.2f}",
        ),
        (
            "risk_cap_enabled",
            config.max_total_open_risk_usd > 0,
            f"max_total_open_risk_usd={config.max_total_open_risk_usd:.2f}",
        ),
    ]
    if require_no_pending_signals:
        checks.append(
            (
                "pending_signals",
                pending_signals == 0,
                f"pending_signals={pending_signals}",
            )
        )
    economics = _economics_metrics(
        config=config,
        monthly_ai_cost_usd=None,
        monthly_ops_cost_usd=None,
        target_net_usd=economic_target_net_usd,
        projected_monthly_gross_usd=economics_projected_monthly_gross_usd,
        auto_project=economics_auto_project,
        projection_window_days=economics_projection_window_days,
        risk_per_trade_usd=economics_risk_per_trade_usd,
    )
    if require_economic_ready:
        checks.append(
            (
                "economic_ready",
                economics["economic_ready"],
                (
                    f"projected_net={economics['projected_monthly_net_usd']:.2f} "
                    f"target={economics['target_net_usd']:.2f}"
                ),
            )
        )
    return {
        "go_live_ready": all(ok for _, ok, _ in checks),
        "closed_trades": trades,
        "avg_r": avg_r,
        "max_drawdown_r": max_drawdown_r,
        "pending_reviews": pending_reviews,
        "pending_signals": pending_signals,
        "checks": checks,
        "economics": economics,
    }


def handle_go_live_check(config: AppConfig, args: argparse.Namespace) -> None:
    metrics = _go_live_metrics(
        config=config,
        min_trades=args.min_trades,
        min_avg_r=args.min_avg_r,
        max_drawdown_r_limit=args.max_drawdown_r,
        require_no_pending_signals=args.require_no_pending_signals,
        require_economic_ready=args.require_economic_ready,
        economic_target_net_usd=args.economic_target_net_usd,
        economics_auto_project=not args.no_economic_auto_project,
        economics_projection_window_days=args.economic_projection_window_days,
        economics_risk_per_trade_usd=args.economic_risk_per_trade_usd,
        economics_projected_monthly_gross_usd=args.economic_projected_monthly_gross_usd,
    )
    economics = metrics["economics"]
    print(f"go_live_ready: {str(metrics['go_live_ready']).lower()}")
    print(f"closed_trades: {metrics['closed_trades']}")
    print(f"avg_r: {metrics['avg_r']:.2f}")
    print(f"max_drawdown_r: {metrics['max_drawdown_r']:.2f}")
    print(f"pending_reviews: {metrics['pending_reviews']}")
    print(f"pending_signals: {metrics['pending_signals']}")
    print(f"max_capital_usd: {config.max_capital_usd:.2f}")
    print(f"max_total_open_risk_usd: {config.max_total_open_risk_usd:.2f}")
    print(f"projected_monthly_gross_usd: {economics['projected_monthly_gross_usd']:.2f}")
    print(f"projected_monthly_net_usd: {economics['projected_monthly_net_usd']:.2f}")
    print(f"economic_target_net_usd: {economics['target_net_usd']:.2f}")
    print(f"economic_projection_mode: {economics['projection_mode']}")
    print("checks:")
    for name, ok, detail in metrics["checks"]:
        print(f"- {name}: {'pass' if ok else 'fail'} ({detail})")


def handle_economics_check(config: AppConfig, args: argparse.Namespace) -> None:
    metrics = _economics_metrics(
        config=config,
        monthly_ai_cost_usd=args.monthly_ai_cost_usd,
        monthly_ops_cost_usd=args.monthly_ops_cost_usd,
        target_net_usd=args.target_net_usd,
        projected_monthly_gross_usd=args.projected_monthly_gross_usd,
        auto_project=not args.no_auto_project,
        projection_window_days=args.projection_window_days,
        risk_per_trade_usd=args.risk_per_trade_usd,
    )
    print(f"economic_ready: {str(metrics['economic_ready']).lower()}")
    print(f"monthly_ai_cost_usd: {metrics['monthly_ai_cost_usd']:.2f}")
    print(f"monthly_ops_cost_usd: {metrics['monthly_ops_cost_usd']:.2f}")
    print(f"monthly_total_cost_usd: {metrics['monthly_total_cost_usd']:.2f}")
    print(f"projected_monthly_gross_usd: {metrics['projected_monthly_gross_usd']:.2f}")
    print(f"projected_monthly_net_usd: {metrics['projected_monthly_net_usd']:.2f}")
    print(f"target_net_usd: {metrics['target_net_usd']:.2f}")
    print(f"required_gross_for_target_usd: {metrics['required_gross_for_target_usd']:.2f}")
    print(f"projection_mode: {metrics['projection_mode']}")
    print(f"projection_window_days: {metrics['projection_window_days']}")
    print(f"projection_risk_per_trade_usd: {metrics['projection_risk_per_trade_usd']:.2f}")
    print(f"window_closed_trades: {metrics['window_closed_trades']}")
    print(f"window_avg_r: {metrics['window_avg_r']:.2f}")
    print(f"window_trades_per_month: {metrics['window_trades_per_month']:.2f}")


def handle_prune_stale_signals(config: AppConfig, args: argparse.Namespace) -> None:
    rows = list_signal_queue(config.signal_queue_path, status="pending")
    if not rows:
        print("No pending signals to prune.")
        return
    now = pd.Timestamp.now(tz="UTC")
    stale = []
    for row in rows:
        created = pd.to_datetime(row.get("created_ts"), utc=True, errors="coerce")
        if pd.isna(created):
            continue
        age_days = (now - created).total_seconds() / 86400
        if age_days >= args.max_age_days:
            stale.append((row["signal_id"], age_days))
    if not stale:
        print("No stale pending signals found.")
        return
    for signal_id, age_days in stale:
        reason = f"stale pending signal age={age_days:.2f}d >= {args.max_age_days:.2f}d"
        if args.dry_run:
            print(f"would_ignore: signal_id={signal_id} reason={reason}")
            continue
        update_signal_status(
            config.signal_queue_path,
            signal_id=signal_id,
            status="ignored",
            decision_reason=reason,
        )
        print(f"ignored_stale: signal_id={signal_id} reason={reason}")


def handle_go_live_snapshot(config: AppConfig, args: argparse.Namespace) -> None:
    metrics = _go_live_metrics(
        config=config,
        min_trades=args.min_trades,
        min_avg_r=args.min_avg_r,
        max_drawdown_r_limit=args.max_drawdown_r,
        require_no_pending_signals=args.require_no_pending_signals,
        require_economic_ready=args.require_economic_ready,
        economic_target_net_usd=args.economic_target_net_usd,
        economics_auto_project=not args.no_economic_auto_project,
        economics_projection_window_days=args.economic_projection_window_days,
        economics_risk_per_trade_usd=args.economic_risk_per_trade_usd,
        economics_projected_monthly_gross_usd=args.economic_projected_monthly_gross_usd,
    )
    economics = metrics["economics"]
    today = date_cls.today().isoformat()
    output_path = args.output or f"knowledge/reviews/go_live_snapshot_{today}.md"
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    lines = [
        f"Go-live snapshot ({today})",
        "",
        f"go_live_ready: {str(metrics['go_live_ready']).lower()}",
        f"closed_trades: {metrics['closed_trades']}",
        f"avg_r: {metrics['avg_r']:.2f}",
        f"max_drawdown_r: {metrics['max_drawdown_r']:.2f}",
        f"pending_reviews: {metrics['pending_reviews']}",
        f"pending_signals: {metrics['pending_signals']}",
        f"max_capital_usd: {config.max_capital_usd:.2f}",
        f"max_total_open_risk_usd: {config.max_total_open_risk_usd:.2f}",
        "",
        "economics:",
        f"- projection_mode: {economics['projection_mode']}",
        f"- projected_monthly_gross_usd: {economics['projected_monthly_gross_usd']:.2f}",
        f"- projected_monthly_net_usd: {economics['projected_monthly_net_usd']:.2f}",
        f"- target_net_usd: {economics['target_net_usd']:.2f}",
        f"- monthly_total_cost_usd: {economics['monthly_total_cost_usd']:.2f}",
        "",
        "checks:",
    ]
    for name, ok, detail in metrics["checks"]:
        lines.append(f"- {name}: {'pass' if ok else 'fail'} ({detail})")
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    print(f"wrote_go_live_snapshot: {output_path}")


def handle_ops_report(config: AppConfig, args: argparse.Namespace) -> None:
    client = AlpacaClient(config)
    open_exposure = _open_exposure_usd(client)
    open_risk = _open_risk_to_stops_usd(client, config.journal_path)
    pending_reviews = len(list_review_queue(config.review_queue_path))
    pending_signals = len(list_signal_queue(config.signal_queue_path, status="pending"))
    metrics = _go_live_metrics(
        config=config,
        min_trades=args.min_trades,
        min_avg_r=args.min_avg_r,
        max_drawdown_r_limit=args.max_drawdown_r,
        require_no_pending_signals=args.require_no_pending_signals,
        require_economic_ready=args.require_economic_ready,
        economic_target_net_usd=args.economic_target_net_usd,
        economics_auto_project=not args.no_economic_auto_project,
        economics_projection_window_days=args.economic_projection_window_days,
        economics_risk_per_trade_usd=args.economic_risk_per_trade_usd,
        economics_projected_monthly_gross_usd=args.economic_projected_monthly_gross_usd,
    )
    economics = metrics["economics"]
    today = date_cls.today().isoformat()
    output_path = args.output or f"knowledge/reviews/ops_{today}.md"
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    lines = [
        f"Ops report ({today})",
        "",
        f"open_exposure_usd: {open_exposure:.2f}",
        f"open_risk_to_stops_usd: {open_risk:.2f}",
        f"max_capital_usd: {config.max_capital_usd:.2f}",
        f"max_total_open_risk_usd: {config.max_total_open_risk_usd:.2f}",
        f"pending_reviews: {pending_reviews}",
        f"pending_signals: {pending_signals}",
        "",
        f"go_live_ready: {str(metrics['go_live_ready']).lower()}",
        f"economic_ready: {str(economics['economic_ready']).lower()}",
        f"projected_monthly_net_usd: {economics['projected_monthly_net_usd']:.2f}",
    ]
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    print(f"wrote_ops_report: {output_path}")


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

    go_live_check_parser = subparsers.add_parser(
        "go-live-check",
        help="Evaluate measurable go-live readiness gates",
    )
    go_live_check_parser.add_argument(
        "--min-trades",
        type=int,
        default=40,
        help="Minimum closed trades required before go-live",
    )
    go_live_check_parser.add_argument(
        "--min-avg-r",
        type=float,
        default=0.10,
        help="Minimum average R across closed trades",
    )
    go_live_check_parser.add_argument(
        "--max-drawdown-r",
        type=float,
        default=5.0,
        help="Maximum allowed drawdown in R units (absolute value)",
    )
    go_live_check_parser.add_argument(
        "--require-no-pending-signals",
        action="store_true",
        help="Fail check if pending signals remain",
    )
    go_live_check_parser.add_argument(
        "--require-economic-ready",
        action="store_true",
        help="Fail check if economic check is not ready",
    )
    go_live_check_parser.add_argument(
        "--economic-target-net-usd",
        type=float,
        default=None,
        help="Override economic target net for go-live gate",
    )
    go_live_check_parser.add_argument(
        "--no-economic-auto-project",
        action="store_true",
        help="Disable auto economics projection from closed trades",
    )
    go_live_check_parser.add_argument(
        "--economic-projection-window-days",
        type=int,
        default=None,
        help="Window for auto economics projection",
    )
    go_live_check_parser.add_argument(
        "--economic-risk-per-trade-usd",
        type=float,
        default=None,
        help="Risk per trade used by economics auto projection",
    )
    go_live_check_parser.add_argument(
        "--economic-projected-monthly-gross-usd",
        type=float,
        default=None,
        help="Manual projected gross used when auto projection is off",
    )
    assess_multi_parser.add_argument(
        "--hot-max-allocation",
        type=float,
        default=0.2,
        help="Max allocation for hot-only signals (for reporting)",
    )

    economics_check_parser = subparsers.add_parser(
        "economics-check",
        help="Evaluate economic viability versus monthly costs",
    )
    economics_check_parser.add_argument(
        "--monthly-ai-cost-usd",
        type=float,
        default=None,
        help="Override monthly AI/tooling cost",
    )
    economics_check_parser.add_argument(
        "--monthly-ops-cost-usd",
        type=float,
        default=None,
        help="Override monthly ops/infrastructure cost",
    )
    economics_check_parser.add_argument(
        "--target-net-usd",
        type=float,
        default=None,
        help="Override required monthly net profit target",
    )
    economics_check_parser.add_argument(
        "--projected-monthly-gross-usd",
        type=float,
        default=None,
        help="Override projected monthly gross trading PnL",
    )
    economics_check_parser.add_argument(
        "--no-auto-project",
        action="store_true",
        help="Disable auto projection from rolling closed-trade stats",
    )
    economics_check_parser.add_argument(
        "--projection-window-days",
        type=int,
        default=None,
        help="Rolling window for auto projection",
    )
    economics_check_parser.add_argument(
        "--risk-per-trade-usd",
        type=float,
        default=None,
        help="Risk per trade for auto projection math",
    )

    prune_stale_parser = subparsers.add_parser(
        "prune-stale-signals",
        help="Ignore pending signals older than a max age",
    )
    prune_stale_parser.add_argument(
        "--max-age-days",
        type=float,
        default=2.0,
        help="Pending signal age threshold in days",
    )
    prune_stale_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be ignored without updating queue",
    )

    go_live_snapshot_parser = subparsers.add_parser(
        "go-live-snapshot",
        help="Write a machine-checked go-live snapshot markdown",
    )
    go_live_snapshot_parser.add_argument(
        "--output",
        default=None,
        help="Snapshot markdown path",
    )
    go_live_snapshot_parser.add_argument(
        "--min-trades",
        type=int,
        default=40,
        help="Minimum closed trades required before go-live",
    )
    go_live_snapshot_parser.add_argument(
        "--min-avg-r",
        type=float,
        default=0.10,
        help="Minimum average R across closed trades",
    )
    go_live_snapshot_parser.add_argument(
        "--max-drawdown-r",
        type=float,
        default=5.0,
        help="Maximum allowed drawdown in R units (absolute value)",
    )
    go_live_snapshot_parser.add_argument(
        "--require-no-pending-signals",
        action="store_true",
        help="Fail check if pending signals remain",
    )
    go_live_snapshot_parser.add_argument(
        "--require-economic-ready",
        action="store_true",
        help="Fail check if economics is not ready",
    )
    go_live_snapshot_parser.add_argument(
        "--economic-target-net-usd",
        type=float,
        default=None,
        help="Override economic target net for go-live gate",
    )
    go_live_snapshot_parser.add_argument(
        "--no-economic-auto-project",
        action="store_true",
        help="Disable auto economics projection from closed trades",
    )
    go_live_snapshot_parser.add_argument(
        "--economic-projection-window-days",
        type=int,
        default=None,
        help="Window for auto economics projection",
    )
    go_live_snapshot_parser.add_argument(
        "--economic-risk-per-trade-usd",
        type=float,
        default=None,
        help="Risk per trade used by economics auto projection",
    )
    go_live_snapshot_parser.add_argument(
        "--economic-projected-monthly-gross-usd",
        type=float,
        default=None,
        help="Manual projected gross used when auto projection is off",
    )

    ops_report_parser = subparsers.add_parser(
        "ops-report",
        help="Write a concise daily operations report",
    )
    ops_report_parser.add_argument(
        "--output",
        default=None,
        help="Ops report markdown path",
    )
    ops_report_parser.add_argument(
        "--min-trades",
        type=int,
        default=40,
        help="Minimum closed trades required before go-live",
    )
    ops_report_parser.add_argument(
        "--min-avg-r",
        type=float,
        default=0.10,
        help="Minimum average R across closed trades",
    )
    ops_report_parser.add_argument(
        "--max-drawdown-r",
        type=float,
        default=5.0,
        help="Maximum allowed drawdown in R units (absolute value)",
    )
    ops_report_parser.add_argument(
        "--require-no-pending-signals",
        action="store_true",
        help="Fail check if pending signals remain",
    )
    ops_report_parser.add_argument(
        "--require-economic-ready",
        action="store_true",
        help="Fail check if economics is not ready",
    )
    ops_report_parser.add_argument(
        "--economic-target-net-usd",
        type=float,
        default=None,
        help="Override economic target net for go-live gate",
    )
    ops_report_parser.add_argument(
        "--no-economic-auto-project",
        action="store_true",
        help="Disable auto economics projection from closed trades",
    )
    ops_report_parser.add_argument(
        "--economic-projection-window-days",
        type=int,
        default=None,
        help="Window for auto economics projection",
    )
    ops_report_parser.add_argument(
        "--economic-risk-per-trade-usd",
        type=float,
        default=None,
        help="Risk per trade used by economics auto projection",
    )
    ops_report_parser.add_argument(
        "--economic-projected-monthly-gross-usd",
        type=float,
        default=None,
        help="Manual projected gross used when auto projection is off",
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
    elif args.command == "go-live-check":
        handle_go_live_check(config, args)
    elif args.command == "economics-check":
        handle_economics_check(config, args)
    elif args.command == "prune-stale-signals":
        handle_prune_stale_signals(config, args)
    elif args.command == "go-live-snapshot":
        handle_go_live_snapshot(config, args)
    elif args.command == "ops-report":
        handle_ops_report(config, args)
    elif args.command == "scan":
        handle_scan(config, args)


if __name__ == "__main__":
    main()
