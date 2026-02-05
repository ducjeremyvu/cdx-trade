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


def _to_ny_timestamp(value: pd.Timestamp) -> str:
    return value.tz_convert("America/New_York").isoformat()


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
