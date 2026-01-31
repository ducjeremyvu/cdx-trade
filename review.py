from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


def _load_trades(journal_path: str) -> pd.DataFrame:
    df = pd.read_csv(journal_path)
    if df.empty:
        return df
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], errors="coerce")
    df["exit_ts"] = pd.to_datetime(df["exit_ts"], errors="coerce")
    df["r_multiple"] = pd.to_numeric(df["r_multiple"], errors="coerce")
    return df


def _load_no_trades(journal_path: str) -> pd.DataFrame:
    df = pd.read_csv(journal_path)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df


def _date_range(anchor_date: str | None, days: int) -> tuple[datetime, datetime]:
    if anchor_date:
        anchor = datetime.fromisoformat(anchor_date)
    else:
        anchor = datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    return start, end


def _summarize(df: pd.DataFrame, no_trades: pd.DataFrame | None = None) -> dict:
    if df.empty:
        no_trade_count = 0
        if no_trades is not None and not no_trades.empty:
            no_trade_count = int(no_trades["timestamp"].notna().sum())
        return {
            "total_trades": 0,
            "closed_trades": 0,
            "open_trades": 0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "no_trades": no_trade_count,
            "most_common_mistake": "no trades",
            "negative_expectancy_setups": "no trades",
            "emotional_pattern": "no trades",
        }

    total_trades = len(df)
    closed = df[df["outcome"].isin(["win", "loss", "scratch"])]
    closed_trades = len(closed)
    open_trades = total_trades - closed_trades
    wins = (closed["outcome"] == "win").sum()
    win_rate = wins / closed_trades if closed_trades else 0.0
    avg_r = closed["r_multiple"].mean(skipna=True) if closed_trades else 0.0

    losses = df[df["outcome"] == "loss"]
    most_common_mistake = (
        losses["what_went_wrong"].mode().iloc[0]
        if not losses.empty and losses["what_went_wrong"].notna().any()
        else "no loss notes"
    )

    expectancy = (
        closed.groupby("setup_name")["r_multiple"].agg(["mean", "count"]).reset_index()
    )
    negative_setups = expectancy[
        (expectancy["count"] >= 3) & (expectancy["mean"] < 0)
    ]["setup_name"].tolist()
    negative_setups_display = negative_setups or ["none"]

    emotional_pattern = (
        losses["emotional_state"].mode().iloc[0]
        if not losses.empty and losses["emotional_state"].notna().any()
        else "no loss emotions"
    )

    no_trade_count = 0
    if no_trades is not None and not no_trades.empty:
        no_trade_count = int(no_trades["timestamp"].notna().sum())

    return {
        "total_trades": total_trades,
        "closed_trades": closed_trades,
        "open_trades": open_trades,
        "win_rate": round(win_rate, 4),
        "avg_r": round(avg_r, 4),
        "no_trades": no_trade_count,
        "most_common_mistake": most_common_mistake,
        "negative_expectancy_setups": ", ".join(negative_setups_display),
        "emotional_pattern": emotional_pattern,
    }


def daily_summary(
    journal_path: str,
    no_trade_path: str | None,
    date_str: str | None,
) -> dict:
    df = _load_trades(journal_path)
    start, end = _date_range(date_str, days=1)
    df = df[(df["entry_ts"] >= start) & (df["entry_ts"] < end)]
    no_trades = None
    if no_trade_path:
        no_trades = _load_no_trades(no_trade_path)
        no_trades = no_trades[
            (no_trades["timestamp"] >= start) & (no_trades["timestamp"] < end)
        ]
    return _summarize(df, no_trades)


def weekly_summary(
    journal_path: str,
    no_trade_path: str | None,
    date_str: str | None,
) -> dict:
    df = _load_trades(journal_path)
    start, end = _date_range(date_str, days=7)
    df = df[(df["entry_ts"] >= start) & (df["entry_ts"] < end)]
    no_trades = None
    if no_trade_path:
        no_trades = _load_no_trades(no_trade_path)
        no_trades = no_trades[
            (no_trades["timestamp"] >= start) & (no_trades["timestamp"] < end)
        ]
    return _summarize(df, no_trades)


def no_trade_summary(
    no_trade_path: str,
    date_str: str | None,
    days: int,
) -> dict:
    df = _load_no_trades(no_trade_path)
    if df.empty:
        return {
            "total_no_trades": 0,
            "top_reason": "no trades",
            "top_context": "no trades",
            "top_emotion": "no trades",
            "reason_counts": [],
        }
    start, end = _date_range(date_str, days=days)
    df = df[(df["timestamp"] >= start) & (df["timestamp"] < end)]
    if df.empty:
        return {
            "total_no_trades": 0,
            "top_reason": "no trades",
            "top_context": "no trades",
            "top_emotion": "no trades",
            "reason_counts": [],
        }

    total_no_trades = int(df["timestamp"].notna().sum())
    top_reason = (
        df["reason"].mode().iloc[0] if df["reason"].notna().any() else "no reason"
    )
    top_context = (
        df["market_context"].mode().iloc[0]
        if df["market_context"].notna().any()
        else "no context"
    )
    top_emotion = (
        df["emotional_state"].mode().iloc[0]
        if df["emotional_state"].notna().any()
        else "no emotion"
    )
    reason_counts = (
        df["reason"]
        .value_counts()
        .head(5)
        .reset_index()
        .values.tolist()
    )
    return {
        "total_no_trades": total_no_trades,
        "top_reason": top_reason,
        "top_context": top_context,
        "top_emotion": top_emotion,
        "reason_counts": reason_counts,
    }


def write_weekly_snapshot(
    journal_path: str,
    no_trade_path: str | None,
    date_str: str | None,
    output_dir: str,
) -> str:
    start, end = _date_range(date_str, days=7)
    summary = weekly_summary(journal_path, no_trade_path, date_str)
    output_dir = output_dir.rstrip("/")
    filename = f"{start.date().isoformat()}_weekly.md"
    path = f"{output_dir}/{filename}"
    week_range = f"{start.date().isoformat()} to {end.date().isoformat()}"

    content = (
        "Weekly review snapshot\n\n"
        f"week_range: {week_range}\n"
        f"total_trades: {summary['total_trades']}\n"
        f"closed_trades: {summary['closed_trades']}\n"
        f"open_trades: {summary['open_trades']}\n"
        f"no_trades: {summary['no_trades']}\n"
        f"win_rate: {summary['win_rate']}\n"
        f"avg_r: {summary['avg_r']}\n"
        f"most_common_mistake: {summary['most_common_mistake']}\n"
        f"negative_expectancy_setups: {summary['negative_expectancy_setups']}\n"
        f"emotional_pattern: {summary['emotional_pattern']}\n"
        "one_change_next_week: \n"
    )

    import os

    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return path
