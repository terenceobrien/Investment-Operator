#!/usr/bin/env python3
"""Pull forward returns for a given ticker over specified periods."""

import yfinance as yf
import pandas as pd


def main():
    # Prompt for inputs
    ticker = input("Enter ticker symbol (e.g., SPY): ").strip().upper()
    start_date = input("Enter start date (YYYY-MM-DD): ").strip()
    end_date = input("Enter end date (YYYY-MM-DD): ").strip()

    # Fetch historical data
    print(f"Fetching data for {ticker} from {start_date} to {end_date}...")
    data = yf.download(ticker, start=start_date, end=end_date, progress=False)

    if data.empty:
        print("No data found for the given ticker and date range.")
        return

    # Use closing prices
    prices = data['Close']

    # Define periods: label -> days
    periods = {
        '1d': 1,
        '1w': 5,
        '1m': 21,
        '3m': 62,
        '6m': 121,
        '1y': 252
    }

    # Compute forward returns
    returns_df = pd.DataFrame(index=prices.index)
    for label, days in periods.items():
        # Forward return: (price[t+days] / price[t]) - 1
        # Shift prices backward by 'days' to align
        future_prices = prices.shift(-days)
        ret = (future_prices / prices) - 1
        returns_df[label] = ret

    # Output CSV
    csv_filename = f"{ticker}_forward_returns_{start_date}_to_{end_date}.csv"
    returns_df.to_csv(csv_filename, index_label='date')
    print(f"Forward returns saved to {csv_filename}")
    print(f"Data shape: {returns_df.shape}")


if __name__ == "__main__":
    main()