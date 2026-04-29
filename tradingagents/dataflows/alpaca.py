from typing import Annotated
from datetime import datetime, timedelta
import os
import pandas as pd


def _data_client():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(
        os.environ["ALPACA_API_KEY"],
        os.environ["ALPACA_SECRET_KEY"],
    )


def _bars_to_df(bars, symbol: str) -> pd.DataFrame:
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol.upper(), level="symbol")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume", "vwap": "VWAP",
        "trade_count": "Trade Count",
    })
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    for col in ("Open", "High", "Low", "Close"):
        if col in df.columns:
            df[col] = df[col].round(2)
    return df


def get_alpaca_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    request = StockBarsRequest(
        symbol_or_symbols=[symbol.upper()],
        timeframe=TimeFrame.Day,
        start=datetime.strptime(start_date, "%Y-%m-%d"),
        end=datetime.strptime(end_date, "%Y-%m-%d"),
    )
    bars = _data_client().get_stock_bars(request)
    df = _bars_to_df(bars, symbol)

    if df.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Total records: {len(df)}\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv()


def get_alpaca_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to compute"],
    curr_date: Annotated[str, "current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    import stockstats
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    # Extra buffer ensures enough bars after weekend/holiday gaps
    start_dt = end_dt - timedelta(days=look_back_days + 60)

    request = StockBarsRequest(
        symbol_or_symbols=[symbol.upper()],
        timeframe=TimeFrame.Day,
        start=start_dt,
        end=end_dt,
    )
    bars = _data_client().get_stock_bars(request)
    df = _bars_to_df(bars, symbol)

    if df.empty:
        return f"No data found for {symbol} to compute {indicator}"

    df.columns = [c.lower() for c in df.columns]
    stock = stockstats.StockDataFrame.retype(df.copy())

    try:
        values = stock[indicator].tail(look_back_days)
    except Exception as e:
        return f"Could not compute indicator '{indicator}' for {symbol}: {e}"

    lines = [f"# {indicator.upper()} for {symbol.upper()} (last {look_back_days} days up to {curr_date})"]
    for date, val in values.items():
        lines.append(f"{date}: {round(float(val), 4)}")
    return "\n".join(lines)


def get_alpaca_latest_price(symbol: str) -> float:
    from alpaca.data.requests import StockLatestQuoteRequest

    client = _data_client()
    quote = client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=[symbol.upper()])
    )
    q = quote[symbol.upper()]
    # Use mid-price; fall back to ask if bid is zero
    bid, ask = float(q.bid_price), float(q.ask_price)
    return (bid + ask) / 2 if bid > 0 else ask
