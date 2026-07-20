from backend.src.narrative.ticker_profiles import get_ticker_profile

# Test tickers across sectors — pick a mix of S&P 500 names
test_tickers = [
    "AAPL", "MSFT", "NVDA",  # tech (in TICKER_PROFILES dict)
    "JPM", "BAC", "GS",       # financials
    "XOM", "CVX", "COP",      # energy
    "UNH", "PFE", "MRK",      # healthcare
    "PG", "KO", "WMT",        # consumer staples
    "CCL", "NCLH", "DIS",     # consumer disc
    "CAT", "DE", "GE",        # industrials
    "LIN", "SHW",             # materials
]

for t in test_tickers:
    p = get_ticker_profile(t)
    if p:
        print(f"{t}: sector={p.get('sector')}, sector_etf={p.get('sector_etf')}")
    else:
        print(f"{t}: NO PROFILE")