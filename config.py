from dataclasses import dataclass
import os

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

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()
        api_key = os.getenv("ALPACA_API_KEY", "").strip()
        api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
        if not api_key or not api_secret:
            raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_API_SECRET")

        paper_env = os.getenv("ALPACA_PAPER", "true").lower()
        paper = paper_env in {"1", "true", "yes", "y"}

        fixed_position_size = int(os.getenv("FIXED_POSITION_SIZE", "1"))
        journal_path = os.getenv("TRADE_JOURNAL_PATH", "data/trade_journal.csv")
        no_trade_journal_path = os.getenv(
            "NO_TRADE_JOURNAL_PATH", "data/no_trade_journal.csv"
        )
        pending_reviews_path = os.getenv(
            "PENDING_REVIEWS_PATH", "data/pending_reviews.csv"
        )
        review_queue_path = os.getenv(
            "REVIEW_QUEUE_PATH", "data/review_queue.csv"
        )
        signal_queue_path = os.getenv(
            "SIGNAL_QUEUE_PATH", "data/signal_queue.csv"
        )
        enabled_setups_raw = os.getenv(
            "ENABLED_SETUPS", "PrevDayBreakout_D1,MeanReversion_D1"
        )
        enabled_setups = [
            value.strip()
            for value in enabled_setups_raw.split(",")
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

        backtest_gate_days = int(os.getenv("BACKTEST_GATE_DAYS", "60"))
        backtest_gate_min_trades = int(os.getenv("BACKTEST_GATE_MIN_TRADES", "10"))
        backtest_gate_min_avg_r = float(os.getenv("BACKTEST_GATE_MIN_AVG_R", "0.0"))
        backtest_gate_min_win_rate = float(
            os.getenv("BACKTEST_GATE_MIN_WIN_RATE", "0.45")
        )
        max_open_positions = int(os.getenv("MAX_OPEN_POSITIONS", "1"))

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
        )
