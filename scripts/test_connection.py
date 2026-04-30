import os
from dotenv import load_dotenv
load_dotenv()

from alpaca.trading.client import TradingClient

paper = os.getenv("ALPACA_PAPER", "true").lower() != "false"
client = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=paper)
acct = client.get_account()

mode = "PAPER" if paper else "LIVE"
print(f"Mode           : {mode}")
print(f"Account status : {acct.status}")
print(f"Portfolio value: ${float(acct.portfolio_value):,.2f}")
print(f"Buying power   : ${float(acct.buying_power):,.2f}")
print(f"Cash           : ${float(acct.cash):,.2f}")
print(f"Equity         : ${float(acct.equity):,.2f}")
print(f"Pattern day    : {acct.pattern_day_trader}")

positions = client.get_all_positions()
print(f"\nOpen positions : {len(positions)}")
for p in positions:
    print(f"  {p.symbol}: {p.qty} shares, P&L ${float(p.unrealized_pl):+.2f}")
