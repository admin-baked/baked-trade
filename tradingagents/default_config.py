import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        # alpaca = live/recent bars (requires ALPACA_API_KEY + ALPACA_SECRET_KEY)
        # Falls back to yfinance automatically if Alpaca keys are not set
        "core_stock_apis": "alpaca,yfinance",       # Options: alpaca, alpha_vantage, yfinance
        "technical_indicators": "alpaca,yfinance",  # Options: alpaca, alpha_vantage, yfinance
        # Alpaca does not provide fundamental or news data — keep yfinance here
        "fundamental_data": "yfinance",             # Options: alpha_vantage, yfinance
        "news_data": "yfinance",                    # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Execution configuration (Alpaca order execution)
    "execution": {
        "enabled": os.getenv("EXECUTION_ENABLED", "false").lower() == "true",
        "paper": os.getenv("ALPACA_PAPER", "true").lower() == "true",
        "max_position_pct": float(os.getenv("MAX_POSITION_PCT", "0.05")),
        "max_daily_drawdown": float(os.getenv("MAX_DAILY_DRAWDOWN", "0.03")),
        "max_open_positions": int(os.getenv("MAX_OPEN_POSITIONS", "10")),
    },
}
