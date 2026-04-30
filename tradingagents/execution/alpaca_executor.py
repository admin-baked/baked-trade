import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    action: Literal["buy", "sell", "hold", "skip"]
    ticker: str
    shares: float = 0.0
    order_id: str = ""
    reason: str = ""


class AlpacaExecutor:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        from alpaca.trading.client import TradingClient
        self.client = TradingClient(api_key, secret_key, paper=paper)
        self.paper = paper
        self.max_position_pct = float(os.getenv("MAX_POSITION_PCT", "0.05"))

    def get_account(self):
        return self.client.get_account()

    def get_all_positions(self) -> list:
        return self.client.get_all_positions()

    def get_position(self, ticker: str):
        try:
            return self.client.get_open_position(ticker.upper())
        except Exception:
            return None

    def _current_price(self, ticker: str) -> float:
        """Use last bar close — more reliable than IEX quotes for free-tier accounts."""
        from datetime import date, timedelta
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        import os, pandas as pd

        data_client = StockHistoricalDataClient(
            os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
        )
        end = date.today()
        start = end - timedelta(days=5)
        req = StockBarsRequest(
            symbol_or_symbols=[ticker.upper()],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker.upper(), level="symbol")
        if df.empty:
            return 0.0
        return float(df["close"].iloc[-1])

    def _calculate_shares(self, ticker: str, account) -> int:
        portfolio_value = float(account.portfolio_value)
        buying_power = float(account.buying_power)
        max_capital = portfolio_value * self.max_position_pct
        available = min(buying_power, max_capital)

        price = self._current_price(ticker)
        if price <= 0:
            return 0
        return int(available / price)

    def execute_signal(self, ticker: str, signal: str) -> OrderResult:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        ticker = ticker.upper()

        if signal == "Hold":
            return OrderResult(action="hold", ticker=ticker)

        account = self.get_account()
        existing = self.get_position(ticker)

        if signal == "Buy":
            if existing is not None:
                return OrderResult(action="skip", ticker=ticker, reason="already_in_position")

            shares = self._calculate_shares(ticker, account)
            if shares < 1:
                return OrderResult(action="skip", ticker=ticker, reason="insufficient_funds")

            order = self.client.submit_order(MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            ))
            logger.info("BUY %s x%d order=%s paper=%s", ticker, shares, order.id, self.paper)
            return OrderResult(action="buy", ticker=ticker, shares=shares, order_id=str(order.id))

        if signal == "Sell":
            if existing is None:
                return OrderResult(action="skip", ticker=ticker, reason="no_position")

            qty = float(existing.qty)
            order = self.client.submit_order(MarketOrderRequest(
                symbol=ticker,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            ))
            logger.info("SELL %s x%.2f order=%s paper=%s", ticker, qty, order.id, self.paper)
            return OrderResult(action="sell", ticker=ticker, shares=qty, order_id=str(order.id))

        return OrderResult(action="skip", ticker=ticker, reason=f"unknown_signal:{signal}")
