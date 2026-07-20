from polygon_data import fetch_universe
from trend_strategy import run

data = fetch_universe(["QQQ"], lookback_days=30)
for ticker, df in data.items():
    bt, stats = run(df)
    print(f"\n===== {ticker} =====")
    print(stats)