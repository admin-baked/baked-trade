"""
Daily trading run (ANALYSIS ONLY) — generates Buy/Sell/Hold signals via
multi-agent debate and reports them to BakedBot for execution.

Execution is handled by the BakedBot TypeScript treasury harness
(src/server/treasury/equity-executor.ts). This script is a pure signal
generator — it never places orders.

Required env vars:
  ALPACA_API_KEY, ALPACA_SECRET_KEY  (for Alpaca market data feeds)
  ANTHROPIC_API_KEY or GOOGLE_API_KEY + LLM_PROVIDER

Optional:
  WATCHLIST=AAPL,MSFT,NVDA           (default: SPY,QQQ,AAPL,MSFT,NVDA)
  LLM_PROVIDER=anthropic
  DEEP_THINK_LLM=glm-4.7
  QUICK_THINK_LLM=glm-4.5-air
  BAKEDBOT_API_URL=https://bakedbot.ai
  TRADING_INGEST_SECRET=<secret>
"""

import logging
import os
import sys
from datetime import date, datetime

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("daily_run")

# --- Config ------------------------------------------------------------------

WATCHLIST = [t.strip() for t in os.getenv("WATCHLIST", "SPY,QQQ,AAPL,MSFT,NVDA").split(",") if t.strip()]
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEEP_THINK_LLM = os.getenv("DEEP_THINK_LLM", "gpt-5.4")
QUICK_THINK_LLM = os.getenv("QUICK_THINK_LLM", "gpt-5.4-mini")
BAKEDBOT_API_URL = os.getenv("BAKEDBOT_API_URL", "https://bakedbot.ai")
TRADING_INGEST_SECRET = os.getenv("TRADING_INGEST_SECRET", "")

# --- Imports -----------------------------------------------------------------

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG


def _normalize_signal(signal: str) -> str:
    """Map analyst-language signals to canonical Buy/Sell/Hold."""
    s = (signal or "").strip().lower()
    if s in ("buy", "overweight", "strong buy", "outperform", "accumulate"):
        return "Buy"
    if s in ("sell", "underweight", "strong sell", "underperform", "reduce"):
        return "Sell"
    return "Hold"


def _report_to_bakedbot(payload: dict) -> None:
    if not TRADING_INGEST_SECRET:
        logger.warning("TRADING_INGEST_SECRET not set — signals not reported to BakedBot")
        return
    try:
        resp = requests.post(
            f"{BAKEDBOT_API_URL}/api/trading/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {TRADING_INGEST_SECRET}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("BakedBot ingest ok: %s (executed=%s)", data.get("date"), data.get("executed", 0))
    except Exception as e:
        logger.warning("BakedBot report failed: %s", e)


def main() -> None:
    trade_date = date.today().isoformat()
    run_id = f"{trade_date}-{os.getpid()}"

    logger.info("=== BakedTrade analysis run | %s | %s ===", trade_date, LLM_PROVIDER.upper())
    logger.info("Watchlist: %s", WATCHLIST)

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
    signal_records: list[dict] = []

    for ticker in WATCHLIST:
        logger.info("Analyzing %s ...", ticker)
        record = {"ticker": ticker, "signal": "Hold", "rawSignal": "", "action": "hold", "shares": 0, "orderId": "", "reason": ""}
        try:
            _, raw_signal = ta.propagate(ticker, trade_date)
            signal = _normalize_signal(raw_signal)
            record["rawSignal"] = str(raw_signal)
            record["signal"] = signal
            logger.info("%s -> %s", ticker, signal)
        except Exception as e:
            logger.exception("Error analyzing %s", ticker)
            record["reason"] = str(e)

        signal_records.append(record)

    # Report signals to BakedBot — execution happens in TypeScript harness
    _report_to_bakedbot({
        "date": trade_date,
        "runId": run_id,
        "completedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paper": os.getenv("ALPACA_PAPER", "true").lower() != "false",
        "account": {"equity": 0, "buyingPower": 0, "cash": 0, "lastEquity": 0, "dayPnl": 0, "dayPnlPct": 0},
        "signals": signal_records,
        "positions": [],
    })

    logger.info("=== Analysis complete — execution delegated to BakedBot ===")


if __name__ == "__main__":
    main()
