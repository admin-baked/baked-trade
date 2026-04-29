import logging
import os
from typing import Tuple

logger = logging.getLogger(__name__)


class RiskControls:
    def __init__(
        self,
        max_position_pct: float = None,
        max_daily_drawdown: float = None,
        max_open_positions: int = None,
    ):
        self.max_position_pct = max_position_pct or float(os.getenv("MAX_POSITION_PCT", "0.05"))
        self.max_daily_drawdown = max_daily_drawdown or float(os.getenv("MAX_DAILY_DRAWDOWN", "0.03"))
        self.max_open_positions = max_open_positions or int(os.getenv("MAX_OPEN_POSITIONS", "10"))

    def check_circuit_breaker(self, account) -> Tuple[bool, float]:
        """Returns (ok, drawdown_pct). ok=False means halt all trading."""
        last_equity = float(account.last_equity)
        if last_equity <= 0:
            return True, 0.0

        equity = float(account.equity)
        drawdown = (last_equity - equity) / last_equity

        if drawdown >= self.max_daily_drawdown:
            logger.warning(
                "Circuit breaker: drawdown %.2f%% >= limit %.2f%%",
                drawdown * 100,
                self.max_daily_drawdown * 100,
            )
            return False, drawdown

        return True, drawdown

    def validate_order(
        self,
        ticker: str,
        signal: str,
        account,
        open_positions: list,
    ) -> Tuple[bool, str]:
        """Returns (approved, rejection_reason). Empty reason = approved."""
        if signal == "Hold":
            return True, ""

        ok, drawdown = self.check_circuit_breaker(account)
        if not ok:
            return False, f"circuit_breaker: daily drawdown {drawdown*100:.2f}% >= {self.max_daily_drawdown*100:.0f}% limit"

        if signal == "Buy":
            # Only block buys — sells/covers should always be allowed
            tickers_held = {p.symbol for p in open_positions}
            if ticker.upper() not in tickers_held and len(open_positions) >= self.max_open_positions:
                return False, f"max_open_positions ({self.max_open_positions}) reached"

        buying_power = float(account.buying_power)
        if signal == "Buy" and buying_power <= 0:
            return False, "no_buying_power"

        return True, ""
