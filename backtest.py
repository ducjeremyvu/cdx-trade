from __future__ import annotations

from dataclasses import dataclass
import os

import pandas as pd

from alpaca_client import AlpacaClient
from regime import detect_regime, regime_allows


@dataclass(frozen=True)
class BacktestResult:
    trades_path: str
    total_trades: int
    win_rate: float
    avg_r: float
    median_r: float
    best_r: float
    worst_r: float


@dataclass(frozen=True)
class PortfolioBacktestResult:
    trades_path: str
    skips_path: str
    signals_path: str
    total_signals: int
    executed_trades: int
    skipped_signals: int
    fill_rate: float
    constrained_win_rate: float
    constrained_avg_r: float
    unconstrained_win_rate: float
    unconstrained_avg_r: float


def _to_ny_timestamp(value: pd.Timestamp) -> str:
    return value.tz_convert("America/New_York").isoformat()


def _signal_triggered(df: pd.DataFrame, signal_index: int, setup_name: str) -> bool:
    prior = df.iloc[signal_index - 1]
    latest = df.iloc[signal_index]
    if setup_name == "PrevDayBreakout_D1":
        return bool(latest["close"] > prior["high"])
    if setup_name == "TwoDayBreakout_D1":
        if signal_index < 2:
            return False
        prior_two = df.iloc[signal_index - 2]
        return bool(latest["close"] > max(prior["high"], prior_two["high"]))
    if setup_name == "MeanReversion_D1":
        return bool(latest["close"] < prior["low"])
    return False


def _simulate_trade(
    df: pd.DataFrame,
    signal_index: int,
    setup_name: str,
    risk_multiple: float,
    time_stop_days: int,
) -> dict | None:
    if signal_index + 1 >= len(df):
        return None
    prior = df.iloc[signal_index - 1]
    latest = df.iloc[signal_index]
    entry_day = df.iloc[signal_index + 1]

    entry_price = entry_day["open"]
    if setup_name == "MeanReversion_D1":
        stop_price = latest["low"]
    elif setup_name == "TwoDayBreakout_D1":
        if signal_index < 2:
            return None
        prior_two = df.iloc[signal_index - 2]
        stop_price = min(prior["low"], prior_two["low"])
    else:
        stop_price = prior["low"]
    if entry_price <= stop_price:
        return None

    risk = entry_price - stop_price
    target_price = entry_price + risk_multiple * risk

    last_index = len(df) - 1
    if time_stop_days > 0:
        last_index = min(last_index, signal_index + time_stop_days)

    exit_price = None
    exit_reason = None
    exit_ts = None
    r_multiple = None

    for idx in range(signal_index + 1, last_index + 1):
        day = df.iloc[idx]
        if day["low"] <= stop_price:
            exit_price = stop_price
            exit_reason = "SL hit"
            exit_ts = _to_ny_timestamp(day["timestamp"])
            r_multiple = -1.0
            break
        if day["high"] >= target_price:
            exit_price = target_price
            exit_reason = "TP hit"
            exit_ts = _to_ny_timestamp(day["timestamp"])
            r_multiple = risk_multiple
            break

    if exit_price is None:
        day = df.iloc[last_index]
        exit_price = day["close"]
        exit_ts = _to_ny_timestamp(day["timestamp"])
        r_multiple = (exit_price - entry_price) / risk
        if r_multiple > 0:
            exit_reason = "time stop win"
        elif r_multiple < 0:
            exit_reason = "time stop loss"
        else:
            exit_reason = "time stop scratch"

    outcome = "win" if r_multiple > 0 else "loss" if r_multiple < 0 else "scratch"

    return {
        "symbol": entry_day["symbol"],
        "setup_name": setup_name,
        "signal_ts": _to_ny_timestamp(latest["timestamp"]),
        "entry_ts": _to_ny_timestamp(entry_day["timestamp"]),
        "entry_price": round(float(entry_price), 4),
        "stop_price": round(float(stop_price), 4),
        "target_price": round(float(target_price), 4),
        "exit_ts": exit_ts,
        "exit_price": round(float(exit_price), 4),
        "exit_reason": exit_reason,
        "r_multiple": round(float(r_multiple), 4),
        "outcome": outcome,
    }


def run_backtest(
    client: AlpacaClient,
    symbol: str,
    start: str,
    end: str,
    risk_multiple: float,
    time_stop_days: int,
    output_path: str,
    setup_name: str = "PrevDayBreakout_D1",
    recent_days: int | None = None,
    regime_filter: dict | None = None,
) -> BacktestResult:
    if risk_multiple <= 0:
        raise ValueError("risk_multiple must be greater than 0")
    if time_stop_days < 1:
        raise ValueError("time_stop_days must be >= 1")
    if setup_name not in {
        "PrevDayBreakout_D1",
        "MeanReversion_D1",
        "TwoDayBreakout_D1",
    }:
        raise ValueError(f"Unsupported setup_name: {setup_name}")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    bars = client.get_daily_bars(symbol, start, end)
    if bars is None or bars.empty:
        raise RuntimeError("No historical data returned for backtest.")

    df = bars.reset_index()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["symbol"] = symbol
    if recent_days is not None:
        keep = recent_days + 2
        if len(df) > keep:
            df = df.iloc[-keep:].reset_index(drop=True)

    trades: list[dict] = []
    for i in range(1, len(df) - 1):
        prior = df.iloc[i - 1]
        latest = df.iloc[i]
        if regime_filter and regime_filter.get("enabled", False):
            regime = detect_regime(
                df.iloc[: i + 1],
                fast_sma=regime_filter.get("fast_sma", 20),
                slow_sma=regime_filter.get("slow_sma", 50),
            )
            if not regime_allows(setup_name, regime):
                continue
        if setup_name == "PrevDayBreakout_D1":
            if latest["close"] <= prior["high"]:
                continue
        elif setup_name == "TwoDayBreakout_D1":
            if i < 2:
                continue
            prior_two = df.iloc[i - 2]
            if latest["close"] <= max(prior["high"], prior_two["high"]):
                continue
        elif setup_name == "MeanReversion_D1":
            if latest["close"] >= prior["low"]:
                continue
        trade = _simulate_trade(df, i, setup_name, risk_multiple, time_stop_days)
        if trade:
            trades.append(trade)

    trades_df = pd.DataFrame(trades)
    trades_df.to_csv(output_path, index=False)

    if trades_df.empty:
        return BacktestResult(
            trades_path=output_path,
            total_trades=0,
            win_rate=0.0,
            avg_r=0.0,
            median_r=0.0,
            best_r=0.0,
            worst_r=0.0,
        )

    total_trades = len(trades_df)
    win_rate = float((trades_df["outcome"] == "win").mean())
    avg_r = float(trades_df["r_multiple"].mean())
    median_r = float(trades_df["r_multiple"].median())
    best_r = float(trades_df["r_multiple"].max())
    worst_r = float(trades_df["r_multiple"].min())

    return BacktestResult(
        trades_path=output_path,
        total_trades=total_trades,
        win_rate=win_rate,
        avg_r=avg_r,
        median_r=median_r,
        best_r=best_r,
        worst_r=worst_r,
    )


def summarize_backtest(trades_path: str) -> dict:
    df = pd.read_csv(trades_path)
    if df.empty:
        return {"yearly": [], "monthly": []}
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True, errors="coerce")
    df = df[df["entry_ts"].notna()].copy()
    df["year"] = df["entry_ts"].dt.year
    df["month"] = df["entry_ts"].dt.tz_convert(None).dt.to_period("M").astype(str)

    yearly = df.groupby("year", as_index=False).agg(
        trades=("r_multiple", "count"),
        win_rate=("outcome", lambda x: (x == "win").mean()),
        avg_r=("r_multiple", "mean"),
    )
    yearly["win_rate"] = yearly["win_rate"].round(2)
    yearly["avg_r"] = yearly["avg_r"].round(2)
    monthly = df.groupby("month", as_index=False).agg(
        trades=("r_multiple", "count"),
        win_rate=("outcome", lambda x: (x == "win").mean()),
        avg_r=("r_multiple", "mean"),
    )
    monthly["win_rate"] = monthly["win_rate"].round(2)
    monthly["avg_r"] = monthly["avg_r"].round(2)
    yearly = yearly.to_dict(orient="records")
    monthly = monthly.to_dict(orient="records")
    return {"yearly": yearly, "monthly": monthly}


def run_portfolio_backtest(
    client: AlpacaClient,
    symbol_setups: list[tuple[str, str]],
    start: str,
    end: str,
    risk_multiple: float,
    time_stop_days: int,
    qty: float,
    max_open_positions: int,
    max_capital_usd: float,
    max_total_open_risk_usd: float,
    output_trades_path: str,
    output_skips_path: str,
    output_signals_path: str,
    regime_filter: dict | None = None,
    rank_by: str = "trailing_avg_r",
    score_lookback_trades: int = 20,
    recent_days: int | None = None,
    min_rank_score: float | None = None,
) -> PortfolioBacktestResult:
    if risk_multiple <= 0:
        raise ValueError("risk_multiple must be greater than 0")
    if time_stop_days < 1:
        raise ValueError("time_stop_days must be >= 1")
    if qty <= 0:
        raise ValueError("qty must be > 0")
    if score_lookback_trades < 1:
        raise ValueError("score_lookback_trades must be >= 1")
    if rank_by not in {"trailing_avg_r", "trailing_blended_avg_r", "none"}:
        raise ValueError(
            "rank_by must be one of: trailing_avg_r, trailing_blended_avg_r, none"
        )

    for path in [output_trades_path, output_skips_path, output_signals_path]:
        output_dir = os.path.dirname(path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

    candidates: list[dict] = []
    for symbol, setup_name in sorted(symbol_setups):
        bars = client.get_daily_bars(symbol, start, end)
        if bars is None or bars.empty:
            continue
        df = bars.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        if recent_days is not None:
            keep = recent_days + 2
            if len(df) > keep:
                df = df.iloc[-keep:].reset_index(drop=True)
        df["symbol"] = symbol

        for i in range(1, len(df) - 1):
            if regime_filter and regime_filter.get("enabled", False):
                regime = detect_regime(
                    df.iloc[: i + 1],
                    fast_sma=regime_filter.get("fast_sma", 20),
                    slow_sma=regime_filter.get("slow_sma", 50),
                )
                if not regime_allows(setup_name, regime):
                    continue
            if not _signal_triggered(df, i, setup_name):
                continue
            trade = _simulate_trade(df, i, setup_name, risk_multiple, time_stop_days)
            if not trade:
                continue
            entry_price = float(trade["entry_price"])
            stop_price = float(trade["stop_price"])
            candidates.append(
                {
                    **trade,
                    "signal_id": f"{symbol}_{setup_name}_{i}",
                    "entry_notional_usd": entry_price * qty,
                    "risk_to_stop_usd": max(0.0, entry_price - stop_price) * qty,
                }
            )

    all_signals_df = pd.DataFrame(candidates)
    all_signals_df.to_csv(output_signals_path, index=False)
    if all_signals_df.empty:
        pd.DataFrame().to_csv(output_trades_path, index=False)
        pd.DataFrame().to_csv(output_skips_path, index=False)
        return PortfolioBacktestResult(
            trades_path=output_trades_path,
            skips_path=output_skips_path,
            signals_path=output_signals_path,
            total_signals=0,
            executed_trades=0,
            skipped_signals=0,
            fill_rate=0.0,
            constrained_win_rate=0.0,
            constrained_avg_r=0.0,
            unconstrained_win_rate=0.0,
            unconstrained_avg_r=0.0,
        )

    all_signals_df["entry_ts"] = pd.to_datetime(
        all_signals_df["entry_ts"], utc=True, errors="coerce"
    )
    all_signals_df["exit_ts"] = pd.to_datetime(
        all_signals_df["exit_ts"], utc=True, errors="coerce"
    )
    all_signals_df["r_multiple"] = pd.to_numeric(
        all_signals_df["r_multiple"], errors="coerce"
    )
    all_signals_df = all_signals_df.sort_values(
        ["entry_ts", "symbol", "setup_name"]
    ).reset_index(drop=True)

    history = (
        all_signals_df[
            ["symbol", "setup_name", "exit_ts", "r_multiple"]
        ]
        .dropna(subset=["exit_ts", "r_multiple"])
        .sort_values(["symbol", "setup_name", "exit_ts"])
    )

    executed: list[dict] = []
    skipped: list[dict] = []
    active_positions: list[dict] = []

    grouped = all_signals_df.groupby("entry_ts", sort=True)
    for entry_ts, group in grouped:
        if pd.isna(entry_ts):
            continue
        active_positions = [
            row for row in active_positions if row["exit_ts"] > entry_ts
        ]
        open_slots = len(active_positions)
        open_exposure = sum(row["entry_notional_usd"] for row in active_positions)
        open_risk = sum(row["risk_to_stop_usd"] for row in active_positions)

        ranked_rows: list[dict] = []
        for _, row in group.iterrows():
            score = 0.0
            if rank_by == "trailing_avg_r":
                hist = history[
                    (history["symbol"] == row["symbol"])
                    & (history["setup_name"] == row["setup_name"])
                    & (history["exit_ts"] < entry_ts)
                ]["r_multiple"].tail(score_lookback_trades)
                score = float(hist.mean()) if not hist.empty else 0.0
            elif rank_by == "trailing_blended_avg_r":
                pair_hist = history[
                    (history["symbol"] == row["symbol"])
                    & (history["setup_name"] == row["setup_name"])
                    & (history["exit_ts"] < entry_ts)
                ]["r_multiple"].tail(score_lookback_trades)
                setup_hist = history[
                    (history["setup_name"] == row["setup_name"])
                    & (history["exit_ts"] < entry_ts)
                ]["r_multiple"].tail(score_lookback_trades)
                symbol_hist = history[
                    (history["symbol"] == row["symbol"])
                    & (history["exit_ts"] < entry_ts)
                ]["r_multiple"].tail(score_lookback_trades)

                pair_score = float(pair_hist.mean()) if not pair_hist.empty else 0.0
                setup_score = (
                    float(setup_hist.mean()) if not setup_hist.empty else 0.0
                )
                symbol_score = (
                    float(symbol_hist.mean()) if not symbol_hist.empty else 0.0
                )
                # Blend pair/setup/symbol expectancy to reduce sparse-history ranking noise.
                score = 0.5 * pair_score + 0.25 * setup_score + 0.25 * symbol_score
            ranked_rows.append(
                {
                    "row": row.to_dict(),
                    "score": score,
                }
            )
        ranked_rows.sort(
            key=lambda item: (
                -item["score"],
                item["row"]["symbol"],
                item["row"]["setup_name"],
                item["row"]["signal_id"],
            )
        )

        for item in ranked_rows:
            row = item["row"]
            score = item["score"]
            signal_id = row["signal_id"]
            symbol = row["symbol"]
            setup_name = row["setup_name"]
            entry_notional_usd = float(row["entry_notional_usd"])
            risk_to_stop_usd = float(row["risk_to_stop_usd"])

            skip_reason = ""
            if (
                min_rank_score is not None
                and min_rank_score > 0
                and max_open_positions > 0
                and score < min_rank_score
            ):
                skip_reason = "low_score"
            elif max_open_positions > 0 and open_slots >= max_open_positions:
                skip_reason = "no_slot"
            elif max_capital_usd > 0 and open_exposure + entry_notional_usd > max_capital_usd:
                skip_reason = "no_capital"
            elif (
                max_total_open_risk_usd > 0
                and open_risk + risk_to_stop_usd > max_total_open_risk_usd
            ):
                skip_reason = "risk_cap"

            if skip_reason:
                skipped.append(
                    {
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "setup_name": setup_name,
                        "entry_ts": row["entry_ts"],
                        "exit_ts": row["exit_ts"],
                        "entry_price": row["entry_price"],
                        "stop_price": row["stop_price"],
                        "r_multiple": row["r_multiple"],
                        "rank_score": round(float(score), 6),
                        "skip_reason": skip_reason,
                        "open_slots": open_slots,
                        "open_exposure_usd": round(open_exposure, 4),
                        "open_risk_usd": round(open_risk, 4),
                        "entry_notional_usd": round(entry_notional_usd, 4),
                        "risk_to_stop_usd": round(risk_to_stop_usd, 4),
                    }
                )
                continue

            executed_row = {
                "signal_id": signal_id,
                "symbol": symbol,
                "setup_name": setup_name,
                "signal_ts": row["signal_ts"],
                "entry_ts": row["entry_ts"],
                "entry_price": row["entry_price"],
                "stop_price": row["stop_price"],
                "target_price": row["target_price"],
                "exit_ts": row["exit_ts"],
                "exit_price": row["exit_price"],
                "exit_reason": row["exit_reason"],
                "outcome": row["outcome"],
                "r_multiple": row["r_multiple"],
                "qty": qty,
                "entry_notional_usd": round(entry_notional_usd, 4),
                "risk_to_stop_usd": round(risk_to_stop_usd, 4),
                "rank_score": round(float(score), 6),
            }
            executed.append(executed_row)
            active_positions.append(
                {
                    "exit_ts": row["exit_ts"],
                    "entry_notional_usd": entry_notional_usd,
                    "risk_to_stop_usd": risk_to_stop_usd,
                }
            )
            open_slots += 1
            open_exposure += entry_notional_usd
            open_risk += risk_to_stop_usd

    executed_df = pd.DataFrame(executed)
    skipped_df = pd.DataFrame(skipped)
    executed_df.to_csv(output_trades_path, index=False)
    skipped_df.to_csv(output_skips_path, index=False)

    total_signals = int(len(all_signals_df))
    executed_trades = int(len(executed_df))
    skipped_signals = int(len(skipped_df))
    fill_rate = (executed_trades / total_signals) if total_signals else 0.0

    unconstrained_win_rate = float((all_signals_df["r_multiple"] > 0).mean())
    unconstrained_avg_r = float(all_signals_df["r_multiple"].mean())
    if executed_df.empty:
        constrained_win_rate = 0.0
        constrained_avg_r = 0.0
    else:
        constrained_win_rate = float((executed_df["r_multiple"] > 0).mean())
        constrained_avg_r = float(executed_df["r_multiple"].mean())

    return PortfolioBacktestResult(
        trades_path=output_trades_path,
        skips_path=output_skips_path,
        signals_path=output_signals_path,
        total_signals=total_signals,
        executed_trades=executed_trades,
        skipped_signals=skipped_signals,
        fill_rate=fill_rate,
        constrained_win_rate=constrained_win_rate,
        constrained_avg_r=constrained_avg_r,
        unconstrained_win_rate=unconstrained_win_rate,
        unconstrained_avg_r=unconstrained_avg_r,
    )


def write_backtest_rollup(
    input_glob: str,
    months: int,
    output_path: str,
) -> str:
    if months < 1:
        raise ValueError("months must be >= 1")
    import pathlib

    paths = list(pathlib.Path().glob(input_glob))

    rows = []
    for path in paths:
        name = path.name
        if name == "backtest_trades.csv":
            continue
        if name.startswith("backtest_gate_") or name.startswith("backtest_recent_"):
            continue
        parts = name.replace("backtest_", "").replace(".csv", "").split("_")
        if len(parts) < 4:
            continue
        symbol = parts[0]
        setup = f"{parts[1]}_{parts[2]}"
        window = parts[3]
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty or "entry_ts" not in df.columns:
            continue
        df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True, errors="coerce")
        df = df[df["entry_ts"].notna()].copy()
        if df.empty:
            continue
        df["symbol"] = symbol
        df["setup"] = setup
        df["window"] = window
        rows.append(df)

    if not rows:
        raise RuntimeError("No backtest CSVs matched the rollup criteria.")

    data = pd.concat(rows, ignore_index=True)
    data["month"] = data["entry_ts"].dt.tz_convert(None).dt.to_period("M")
    max_month = data["month"].max()
    min_month = max_month - (months - 1)
    data = data[data["month"] >= min_month]

    grouped = (
        data.groupby(["month", "symbol", "setup", "window"], as_index=False)
        .agg(
            trades=("r_multiple", "count"),
            win_rate=("outcome", lambda x: (x == "win").mean()),
            avg_r=("r_multiple", "mean"),
            median_r=("r_multiple", "median"),
        )
        .sort_values(["month", "symbol", "setup", "window"])
    )
    grouped["month"] = grouped["month"].astype(str)
    grouped["win_rate"] = grouped["win_rate"].round(2)
    grouped["avg_r"] = grouped["avg_r"].round(2)
    grouped["median_r"] = grouped["median_r"].round(2)

    lines = []
    lines.append("Monthly backtest rollup")
    lines.append("")
    lines.append(f"source_glob: {input_glob}")
    lines.append(f"months: {months}")
    lines.append("")
    lines.append(
        "| month | symbol | setup | window | trades | win_rate | avg_r | median_r |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for _, row in grouped.iterrows():
        lines.append(
            f"| {row['month']} | {row['symbol']} | {row['setup']} | {row['window']} | "
            f"{int(row['trades'])} | {row['win_rate']:.2f} | {row['avg_r']:.2f} | {row['median_r']:.2f} |"
        )

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return output_path


def run_recent_backtest(
    client: AlpacaClient,
    symbol: str,
    recent_days: int,
    risk_multiple: float,
    time_stop_days: int,
    output_path: str,
    setup_name: str,
    regime_filter: dict | None = None,
) -> BacktestResult:
    end = pd.Timestamp.now(tz="UTC").date().isoformat()
    start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=recent_days * 3)).date()
    return run_backtest(
        client=client,
        symbol=symbol,
        start=start.isoformat(),
        end=end,
        risk_multiple=risk_multiple,
        time_stop_days=time_stop_days,
        output_path=output_path,
        setup_name=setup_name,
        recent_days=recent_days,
        regime_filter=regime_filter,
    )
