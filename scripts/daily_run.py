"""
Daily trading run — meant to be triggered by Cloud Scheduler at 9:35 AM ET (14:35 UTC) Mon–Fri.

Required env vars:
  ALPACA_API_KEY, ALPACA_SECRET_KEY
  OPENAI_API_KEY (or ANTHROPIC_API_KEY / GOOGLE_API_KEY + LLM_PROVIDER)

Optional:
  ALPACA_PAPER=true          (default: true — never goes live unless explicitly false)
  EXECUTION_ENABLED=true     (default: false — analysis-only unless explicitly true)
  WATCHLIST=AAPL,MSFT,NVDA   (default: SPY,QQQ,AAPL,MSFT,NVDA)
  MAX_POSITION_PCT=0.05
  MAX_DAILY_DRAWDOWN=0.03
  MAX_OPEN_POSITIONS=10
  SLACK_WEBHOOK_URL=
  LLM_PROVIDER=openai
"""

import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("daily_run")

# --- Config -----------------------------------------------------------------

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() != "false"
EXECUTION_ENABLED = os.getenv("EXECUTION_ENABLED", "false").lower() == "true"
WATCHLIST = [t.strip() for t in os.getenv("WATCHLIST", "SPY,QQQ,AAPL,MSFT,NVDA").split(",") if t.strip()]
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# --- Imports after env is loaded --------------------------------------------

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.alpaca_executor import AlpacaExecutor
from tradingagents.execution.risk_controls import RiskControls
from tradingagents.execution.notifier import SlackNotifier


def main() -> None:
    trade_date = date.today().isoformat()
    mode = "PAPER" if ALPACA_PAPER else "LIVE"
    exec_label = "EXECUTING" if EXECUTION_ENABLED else "ANALYSIS ONLY"

    logger.info("=== BakedTrade daily run | %s | %s | %s ===", trade_date, mode, exec_label)
    logger.info("Watchlist: %s", WATCHLIST)

    notifier = SlackNotifier()
    executor = AlpacaExecutor(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER) if EXECUTION_ENABLED else None
    risk = RiskControls()

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = LLM_PROVIDER
    config["data_vendors"] = {
        "core_stock_apis": "alpaca,yfinance",
        "technical_indicators": "alpaca,yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }

    ta = TradingAgentsGraph(debug=False, config=config)

    # Pre-flight: circuit breaker check
    if EXECUTION_ENABLED:
        try:
            account = executor.get_account()
            ok, drawdown = risk.check_circuit_breaker(account)
            if not ok:
                notifier.notify_circuit_breaker(drawdown * 100, float(account.equity))
                logger.error("Circuit breaker tripped — aborting run")
                sys.exit(1)
        except Exception as e:
            notifier.notify_error(str(e), "pre-flight account check")
            logger.exception("Pre-flight failed")
            sys.exit(1)

    # Per-ticker analysis + execution
    for ticker in WATCHLIST:
        logger.info("Analyzing %s ...", ticker)
        try:
            _, signal = ta.propagate(ticker, trade_date)
            logger.info("%s → %s", ticker, signal)

            if not EXECUTION_ENABLED:
                continue

            positions = executor.get_all_positions()
            account = executor.get_account()

            approved, rejection = risk.validate_order(ticker, signal, account, positions)
            if not approved:
                logger.warning("Order rejected for %s: %s", ticker, rejection)
                notifier.notify_skipped(ticker, signal, rejection)
                continue

            result = executor.execute_signal(ticker, signal)

            if result.action in ("buy", "sell"):
                notifier.notify_order(ticker, result.action, result.shares, result.order_id, ALPACA_PAPER)
            elif result.action == "skip":
                notifier.notify_skipped(ticker, signal, result.reason)

        except Exception as e:
            logger.exception("Error processing %s", ticker)
            notifier.notify_error(str(e), ticker)

    # End-of-run summary
    if EXECUTION_ENABLED:
        try:
            account = executor.get_account()
            positions = executor.get_all_positions()
            notifier.notify_daily_summary(account, positions)
        except Exception as e:
            logger.warning("Could not send daily summary: %s", e)

    logger.info("=== Run complete ===")


if __name__ == "__main__":
    main()
