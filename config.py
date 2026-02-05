from dataclasses import dataclass
import json
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    api_secret: str
    paper: bool
    fixed_position_size: int
    journal_path: str
    no_trade_journal_path: str
    pending_reviews_path: str
    review_queue_path: str
    signal_queue_path: str
    enabled_setups: list[str]
    setups_by_symbol: dict[str, list[str]]
    backtest_gate_days: int
    backtest_gate_min_trades: int
    backtest_gate_min_avg_r: float
    backtest_gate_min_win_rate: float
    max_open_positions: int
    watch_only_symbols: list[str]
    universe_path: str
    regime_filter_enabled: bool
    regime_fast_sma: int
    regime_slow_sma: int
    allowlist_only: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()
        config_path = os.getenv("CONFIG_PATH", "config.json").strip() or "config.json"
        config_data = {}
        config_file = Path(config_path)
        if config_file.exists():
            with config_file.open("r", encoding="utf-8") as file:
                config_data = json.load(file)

        api_key = os.getenv("ALPACA_API_KEY", "").strip()
        api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
        if not api_key or not api_secret:
            raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_API_SECRET")

        paper_env = os.getenv("ALPACA_PAPER", "true").lower()
        paper = paper_env in {"1", "true", "yes", "y"}

        fixed_position_size = int(
            os.getenv(
                "FIXED_POSITION_SIZE",
                str(config_data.get("fixed_position_size", 1)),
            )
        )
        journal_path = os.getenv(
            "TRADE_JOURNAL_PATH",
            config_data.get("journal_path", "data/trade_journal.csv"),
        )
        no_trade_journal_path = os.getenv(
            "NO_TRADE_JOURNAL_PATH",
            config_data.get("no_trade_journal_path", "data/no_trade_journal.csv"),
        )
        pending_reviews_path = os.getenv(
            "PENDING_REVIEWS_PATH",
            config_data.get("pending_reviews_path", "data/pending_reviews.csv"),
        )
        review_queue_path = os.getenv(
            "REVIEW_QUEUE_PATH",
            config_data.get("review_queue_path", "data/review_queue.csv"),
        )
        signal_queue_path = os.getenv(
            "SIGNAL_QUEUE_PATH",
            config_data.get("signal_queue_path", "data/signal_queue.csv"),
        )
        enabled_setups_raw = os.getenv("ENABLED_SETUPS", "").strip()
        if enabled_setups_raw:
            enabled_setups = [
                value.strip()
                for value in enabled_setups_raw.split(",")
                if value.strip()
            ]
        else:
            enabled_setups = [
                value.strip()
                for value in config_data.get(
                    "enabled_setups",
                    ["PrevDayBreakout_D1", "MeanReversion_D1", "TwoDayBreakout_D1"],
                )
                if value.strip()
            ]

        setups_by_symbol_raw = os.getenv("SETUPS_BY_SYMBOL", "").strip()
        setups_by_symbol: dict[str, list[str]] = {}
        if setups_by_symbol_raw:
            pairs = [pair.strip() for pair in setups_by_symbol_raw.split(";") if pair]
            for pair in pairs:
                if "=" not in pair:
                    continue
                symbol, setups_raw = pair.split("=", 1)
                setups = [
                    value.strip()
                    for value in setups_raw.split(",")
                    if value.strip()
                ]
                if symbol.strip() and setups:
                    setups_by_symbol[symbol.strip().upper()] = setups

        else:
            setups_by_symbol = {
                symbol.strip().upper(): [
                    setup.strip()
                    for setup in setups
                    if setup.strip()
                ]
                for symbol, setups in config_data.get("setups_by_symbol", {}).items()
                if symbol.strip()
            }

        backtest_gate_days = int(
            os.getenv(
                "BACKTEST_GATE_DAYS",
                str(config_data.get("backtest_gate_days", 90)),
            )
        )
        backtest_gate_min_trades = int(
            os.getenv(
                "BACKTEST_GATE_MIN_TRADES",
                str(config_data.get("backtest_gate_min_trades", 15)),
            )
        )
        backtest_gate_min_avg_r = float(
            os.getenv(
                "BACKTEST_GATE_MIN_AVG_R",
                str(config_data.get("backtest_gate_min_avg_r", 0.10)),
            )
        )
        backtest_gate_min_win_rate = float(
            os.getenv(
                "BACKTEST_GATE_MIN_WIN_RATE",
                str(config_data.get("backtest_gate_min_win_rate", 0.48)),
            )
        )
        max_open_positions = int(
            os.getenv(
                "MAX_OPEN_POSITIONS",
                str(config_data.get("max_open_positions", 1)),
            )
        )
        watch_only_symbols_raw = os.getenv("WATCH_ONLY_SYMBOLS", "").strip()
        if watch_only_symbols_raw:
            watch_only_symbols = [
                value.strip().upper()
                for value in watch_only_symbols_raw.split(",")
                if value.strip()
            ]
        else:
            watch_only_symbols = [
                value.strip().upper()
                for value in config_data.get("watch_only_symbols", [])
                if value.strip()
            ]

        universe_path = os.getenv(
            "UNIVERSE_PATH",
            config_data.get("universe_path", "data/universe.txt"),
        )
        regime_filter_enabled = (
            os.getenv("REGIME_FILTER_ENABLED", "")
            or str(config_data.get("regime_filter_enabled", "false"))
        ).lower() in {"1", "true", "yes", "y"}
        regime_fast_sma = int(
            os.getenv(
                "REGIME_FAST_SMA",
                str(config_data.get("regime_fast_sma", 20)),
            )
        )
        regime_slow_sma = int(
            os.getenv(
                "REGIME_SLOW_SMA",
                str(config_data.get("regime_slow_sma", 50)),
            )
        )
        allowlist_only = (
            os.getenv("ALLOWLIST_ONLY", "")
            or str(config_data.get("allowlist_only", "false"))
        ).lower() in {"1", "true", "yes", "y"}

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            paper=paper,
            fixed_position_size=fixed_position_size,
            journal_path=journal_path,
            no_trade_journal_path=no_trade_journal_path,
            pending_reviews_path=pending_reviews_path,
            review_queue_path=review_queue_path,
            signal_queue_path=signal_queue_path,
            enabled_setups=enabled_setups,
            setups_by_symbol=setups_by_symbol,
            backtest_gate_days=backtest_gate_days,
            backtest_gate_min_trades=backtest_gate_min_trades,
            backtest_gate_min_avg_r=backtest_gate_min_avg_r,
            backtest_gate_min_win_rate=backtest_gate_min_win_rate,
            max_open_positions=max_open_positions,
            watch_only_symbols=watch_only_symbols,
            universe_path=universe_path,
            regime_filter_enabled=regime_filter_enabled,
            regime_fast_sma=regime_fast_sma,
            regime_slow_sma=regime_slow_sma,
            allowlist_only=allowlist_only,
        )
