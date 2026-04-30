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

import requests

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
BAKEDBOT_API_URL = os.getenv("BAKEDBOT_API_URL", "https://bakedbot.ai")
TRADING_INGEST_SECRET = os.getenv("TRADING_INGEST_SECRET", "")
DEEP_THINK_LLM = os.getenv("DEEP_THINK_LLM", "gpt-5.4")
QUICK_THINK_LLM = os.getenv("QUICK_THINK_LLM", "gpt-5.4-mini")

# --- Imports after env is loaded --------------------------------------------

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.alpaca_executor import AlpacaExecutor
from tradingagents.execution.risk_controls import RiskControls
from tradingagents.execution.notifier import SlackNotifier


def _report_to_bakedbot(payload: dict) -> None:
    if not TRADING_INGEST_SECRET:
        logger.debug("TRADING_INGEST_SECRET not set — skipping BakedBot report")
        return
    try:
        resp = requests.post(
            f"{BAKEDBOT_API_URL}/api/trading/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {TRADING_INGEST_SECRET}"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Reported to BakedBot: %s", resp.json())
    except Exception as e:
        logger.warning("BakedBot report failed: %s", e)


def _normalize_signal(signal: str) -> str:
    """Map analyst-language signals to canonical Buy/Sell/Hold."""
    s = (signal or "").strip().lower()
    if s in ("buy", "overweight", "strong buy", "outperform", "accumulate"):
        return "Buy"
    if s in ("sell", "underweight", "strong sell", "underperform", "reduce"):
        return "Sell"
    return "Hold"


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
    config["deep_think_llm"] = DEEP_THINK_LLM
    config["quick_think_llm"] = QUICK_THINK_LLM
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

    run_id = f"{trade_date}-{os.getpid()}"
    signal_records: list[dict] = []

    # Per-ticker analysis + execution
    for ticker in WATCHLIST:
        logger.info("Analyzing %s ...", ticker)
        record = {"ticker": ticker, "signal": "Hold", "rawSignal": "", "action": "hold", "shares": 0, "orderId": "", "reason": ""}
        try:
            _, raw_signal = ta.propagate(ticker, trade_date)
            signal = _normalize_signal(raw_signal)
            record["rawSignal"] = str(raw_signal)
            record["signal"] = signal
            logger.info("%s -> %s", ticker, signal)

            if EXECUTION_ENABLED:
                positions = executor.get_all_positions()
                account = executor.get_account()

                approved, rejection = risk.validate_order(ticker, signal, account, positions)
                if not approved:
                    logger.warning("Order rejected for %s: %s", ticker, rejection)
                    notifier.notify_skipped(ticker, signal, rejection)
                    record["action"] = "skip"
                    record["reason"] = rejection
                else:
                    result = executor.execute_signal(ticker, signal)
                    record["action"] = result.action
                    record["shares"] = result.shares
                    record["orderId"] = result.order_id
                    record["reason"] = result.reason
                    if result.action in ("buy", "sell"):
                        notifier.notify_order(ticker, result.action, result.shares, result.order_id, ALPACA_PAPER)
                    elif result.action == "skip":
                        notifier.notify_skipped(ticker, signal, result.reason)

        except Exception as e:
            logger.exception("Error processing %s", ticker)
            notifier.notify_error(str(e), ticker)
            record["reason"] = str(e)

        signal_records.append(record)

    # Snapshot account + positions for reporting
    account_snapshot = {"equity": 0, "buyingPower": 0, "cash": 0, "lastEquity": 0, "dayPnl": 0, "dayPnlPct": 0}
    position_records: list[dict] = []
    try:
        acct_client = AlpacaExecutor(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER)
        acct = acct_client.get_account()
        equity = float(acct.equity)
        last_equity = float(acct.last_equity)
        day_pnl = equity - last_equity
        account_snapshot = {
            "equity": equity,
            "buyingPower": float(acct.buying_power),
            "cash": float(acct.cash),
            "lastEquity": last_equity,
            "dayPnl": day_pnl,
            "dayPnlPct": (day_pnl / last_equity * 100) if last_equity > 0 else 0,
        }
        for p in acct_client.get_all_positions():
            position_records.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "currentPrice": float(p.current_price or 0),
                "unrealizedPl": float(p.unrealized_pl or 0),
                "unrealizedPlPct": float(p.unrealized_plpc or 0) * 100,
            })
    except Exception as e:
        logger.warning("Could not snapshot account: %s", e)

    # End-of-run summary notification
    if EXECUTION_ENABLED and executor:
        try:
            notifier.notify_daily_summary(executor.get_account(), executor.get_all_positions())
        except Exception as e:
            logger.warning("Could not send daily summary: %s", e)

    # Report to BakedBot dashboard
    _report_to_bakedbot({
        "date": trade_date,
        "runId": run_id,
        "completedAt": date.today().isoformat() + "T" + __import__("datetime").datetime.utcnow().strftime("%H:%M:%SZ"),
        "paper": ALPACA_PAPER,
        "account": account_snapshot,
        "signals": signal_records,
        "positions": position_records,
    })

    logger.info("=== Run complete ===")


if __name__ == "__main__":
    main()
