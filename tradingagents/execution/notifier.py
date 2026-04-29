import logging
import os
from datetime import datetime
from typing import List

import requests

logger = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")

    def _send(self, text: str) -> None:
        if not self.webhook_url:
            logger.debug("Slack webhook not configured — skipping notification")
            return
        try:
            resp = requests.post(self.webhook_url, json={"text": text}, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Slack notification failed: %s", e)

    def notify_order(self, ticker: str, action: str, shares: float, order_id: str = "", paper: bool = True) -> None:
        mode = "📋 PAPER" if paper else "💰 LIVE"
        emoji = "🟢" if action == "buy" else "🔴"
        self._send(
            f"{emoji} {mode} ORDER\n"
            f"*{action.upper()}* {ticker} × {shares:g}\n"
            f"Order ID: `{order_id}`\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

    def notify_skipped(self, ticker: str, signal: str, reason: str) -> None:
        self._send(f"⏭️ SKIPPED {ticker} ({signal}) — {reason}")

    def notify_circuit_breaker(self, drawdown_pct: float, equity: float) -> None:
        self._send(
            f"🛑 *CIRCUIT BREAKER TRIPPED*\n"
            f"Daily drawdown: *{drawdown_pct:.2f}%*\n"
            f"Current equity: ${equity:,.2f}\n"
            f"All new orders halted for today."
        )

    def notify_daily_summary(self, account, positions: List) -> None:
        equity = float(account.equity)
        last_equity = float(account.last_equity)
        day_pnl = equity - last_equity
        day_pnl_pct = (day_pnl / last_equity * 100) if last_equity > 0 else 0
        pnl_emoji = "📈" if day_pnl >= 0 else "📉"

        pos_lines = "\n".join(
            f"  • {p.symbol}: {p.qty} shares @ ${float(p.current_price):.2f} "
            f"(P&L: ${float(p.unrealized_pl):+.2f})"
            for p in positions
        ) or "  No open positions"

        self._send(
            f"{pnl_emoji} *Daily Summary* — {datetime.utcnow().strftime('%Y-%m-%d')}\n"
            f"Equity: ${equity:,.2f} ({day_pnl:+.2f} / {day_pnl_pct:+.2f}% today)\n"
            f"Open positions ({len(positions)}):\n{pos_lines}"
        )

    def notify_error(self, error: str, context: str = "") -> None:
        ctx = f" [{context}]" if context else ""
        self._send(f"🚨 *ERROR*{ctx}\n```{error}```")
