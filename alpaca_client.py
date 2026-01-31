from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from alpaca.data import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetCalendarRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce

import pandas as pd

from config import AppConfig


@dataclass(frozen=True)
class AlpacaOrderResult:
    order_id: str
    filled_avg_price: float | None
    limit_price: float | None
    created_at: str


class AlpacaClient:
    def __init__(self, config: AppConfig) -> None:
        self._trading = TradingClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
            paper=config.paper,
        )
        self._data = StockHistoricalDataClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
        )

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> AlpacaOrderResult:
        if order_type == "limit" and limit_price is None:
            raise ValueError("limit_price is required for limit orders")

        if order_type == "market":
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
        else:
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price,
            )

        order = self._trading.submit_order(request)
        refreshed = self._trading.get_order_by_id(order.id)
        return AlpacaOrderResult(
            order_id=order.id,
            filled_avg_price=(
                float(refreshed.filled_avg_price)
                if refreshed.filled_avg_price
                else None
            ),
            limit_price=(
                float(refreshed.limit_price) if refreshed.limit_price else None
            ),
            created_at=(
                refreshed.created_at.isoformat() if refreshed.created_at else ""
            ),
        )

    def get_order(self, order_id: str):
        return self._trading.get_order_by_id(order_id)

    def list_recent_orders(self, limit: int = 50, status: str = "closed"):
        request = GetOrdersRequest(status=status, limit=limit)
        return self._trading.get_orders(request)

    def get_clock(self):
        return self._trading.get_clock()

    def get_calendar(self, start_date: str, end_date: str):
        request = GetCalendarRequest(start=start_date, end=end_date)
        return self._trading.get_calendar(request)

    def close_position(self, symbol: str):
        return self._trading.close_position(symbol)

    def get_recent_daily_bars(self, symbol: str, days: int = 10):
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex",
        )
        bars = self._data.get_stock_bars(request)
        df = bars.df
        if df is None or df.empty:
            return None
        if isinstance(df.index, pd.MultiIndex):
            return df.xs(symbol, level=0)
        if "symbol" in df.columns:
            return df[df["symbol"] == symbol]
        return df

    def get_daily_bars(self, symbol: str, start: str, end: str):
        start_dt = pd.to_datetime(start, utc=True).to_pydatetime()
        end_dt = pd.to_datetime(end, utc=True).to_pydatetime()
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start_dt,
            end=end_dt,
            feed="iex",
        )
        bars = self._data.get_stock_bars(request)
        df = bars.df
        if df is None or df.empty:
            return None
        if isinstance(df.index, pd.MultiIndex):
            return df.xs(symbol, level=0)
        if "symbol" in df.columns:
            return df[df["symbol"] == symbol]
        return df
