"""
Intraday trend-pullback strategy — backtesting.py skeleton.

Encodes four pillars:
  1. Trend-following direction (no counter-trend / reversal timing)
  2. Trend-STRENGTH gate  -> the "proprietary score" slot (isolated in trend_strength())
  3. Low-volume pullback entry
  4. Time-of-day window (skip open noise + thin mid-day)

Every TBD number is a class-level parameter so you can Backtest.optimize() over it.
Data assumptions:
  - DataFrame indexed by tz-aware DatetimeIndex (intraday bars, e.g. 1-min or 5-min)
  - Columns: Open, High, Low, Close, Volume  (capitalized — backtesting.py requirement)
  - Regular-session bars only (pre-filter RTH before passing in; see load notes at bottom)

Design intent: fail loud, keep direction and strength independent, no lookahead.
Entries are MARKET orders -> filled at NEXT bar open by backtesting.py. Signals are
computed on the CLOSED bar; execution is therefore never same-bar-as-signal.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtesting import Backtest, Strategy
from backtesting.lib import crossover  # noqa: F401  (handy if you swap in crossover logic)


# ---------------------------------------------------------------------------
# Indicator helpers (plain numpy/pandas; wrapped via self.I in the Strategy)
# ---------------------------------------------------------------------------
def ema(x: pd.Series, n: int) -> pd.Series:
    return pd.Series(x).ewm(span=n, adjust=False).mean()


def atr(high, low, close, n: int) -> pd.Series:
    high, low, close = map(pd.Series, (high, low, close))
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def adx(high, low, close, n: int) -> pd.Series:
    """Standard Wilder ADX — trend-strength magnitude, direction-agnostic."""
    high, low, close = map(pd.Series, (high, low, close))
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = atr(high, low, close, n)
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(span=n, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(span=n, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(span=n, adjust=False).mean()


def rolling_vol_mean(volume, n: int) -> pd.Series:
    return pd.Series(volume).rolling(n).mean()


def session_open_price(open_, index: pd.DatetimeIndex) -> np.ndarray:
    """For each bar, the OPEN price of that bar's own session (first bar of the day).
    Used to measure intraday return: current price vs today's open, no higher TF."""
    o = pd.Series(np.asarray(open_, dtype=float), index=pd.DatetimeIndex(index))
    day = pd.DatetimeIndex(index).normalize()
    # first open of each day, forward-filled across that day's bars
    first_open = o.groupby(day).transform("first")
    return first_open.to_numpy()


def prior_session_close(close_, index: pd.DatetimeIndex) -> np.ndarray:
    """For each bar, the CLOSE of the prior session (for gap-inclusive direction).
    First day has no prior close -> NaN (handled as flat)."""
    c = pd.Series(np.asarray(close_, dtype=float), index=pd.DatetimeIndex(index))
    day = pd.DatetimeIndex(index).normalize()
    last_close = c.groupby(day).transform("last")
    # map each day to the previous day's last close
    per_day_last = c.groupby(day).last()
    prev = per_day_last.shift(1)
    mapped = pd.Series(day, index=c.index).map(prev)
    return mapped.to_numpy()


def minutes_since_open(index: pd.DatetimeIndex, open_time="09:30") -> np.ndarray:
    """Minutes elapsed since the session open FOR EACH BAR's own date.
    Assumes US equity RTH. Adjust open_time for other sessions."""
    idx = pd.DatetimeIndex(index)
    oh, om = map(int, open_time.split(":"))
    open_stamp = idx.normalize() + pd.Timedelta(hours=oh, minutes=om)
    # localize open_stamp to the data's tz if tz-aware
    if idx.tz is not None and open_stamp.tz is None:
        open_stamp = open_stamp.tz_localize(idx.tz)
    return (idx - open_stamp) / pd.Timedelta(minutes=1)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------
class TrendPullback(Strategy):
    # ---- Pillar 1: trend direction (intraday return only, no higher TF) ----
    # direction = sign of today's return. basis: "open" (since today's open) or
    # "prior_close" (gap-inclusive). "open" is the purest intraday read.
    dir_basis = "open"
    dir_min_move = 0.0        # optional deadband: require |return| >= this frac
                              # (e.g. 0.001 = 0.1%) before enabling a side; 0 = any sign

    # ---- Pillar 2: trend-STRENGTH gate (the proprietary-score slot) ----
    adx_period = 14
    adx_min = 25.0            # gate: require ADX >= this to trade at all
    trend_dist_atr_min = 0.5  # gate: |close - today's open| in ATR units >= this
    atr_period = 14

    # ---- Pillar 3: low-volume pullback ----
    pullback_lookback = 5     # bars over which to detect the retrace
    pullback_atr_min = 0.4    # retrace must be at least this many ATRs...
    pullback_atr_max = 2.0    # ...but not more (that's a trend break, not a pullback)
    vol_lookback = 20         # baseline volume window
    pullback_vol_ratio = 0.8  # pullback bars' avg vol must be < ratio * baseline

    # ---- Pillar 4: time-of-day window (minutes after open) ----
    entry_start_min = 30      # no entries before open+30
    entry_end_min = 180       # no NEW entries after open+180
    force_flat_min = 210      # close everything by open+210 (no overnight)

    # ---- risk (distances in UNDERLYING price / ATR units) ----
    # NOTE: this backtest simulates the UNDERLYING, not options. A tighter
    # underlying stop roughly implies a tighter effective option stop, but a
    # true premium-based stop needs option data (not on stock Starter). Tightened
    # from 1.5 -> 0.75 for options-style risk; target widened to let convex
    # winners run (set target_atr=None to hold to force-flat instead).
    stop_atr = 1.0          # initial stop distance in ATR (tight)
    target_atr = 2.0        # take-profit in ATR; 3:1 vs the tight stop

    def init(self):
        c, h, l, v = self.data.Close, self.data.High, self.data.Low, self.data.Volume
        o = self.data.Open

        self.atr = self.I(atr, h, l, c, self.atr_period)
        self.adx = self.I(adx, h, l, c, self.adx_period)
        self.vol_ma = self.I(rolling_vol_mean, v, self.vol_lookback)

        # intraday-return reference lines (no higher timeframe)
        self.sess_open = self.I(session_open_price, o, self.data.index,
                                name="session_open")
        self.prev_close = self.I(prior_session_close, c, self.data.index,
                                 name="prior_close")

        # minutes-since-open as an aligned indicator (so it's bar-synced)
        self.mso = self.I(
            lambda: minutes_since_open(self.data.index), name="mins_since_open"
        )

    # ---- Pillar 1: direction = sign of TODAY's return only. No EMAs, no
    #      higher timeframe. Long only if up on the day, short only if down. ----
    def _trend_dir(self) -> int:
        ref = self.sess_open[-1] if self.dir_basis == "open" else self.prev_close[-1]
        if not np.isfinite(ref) or ref <= 0:
            return 0  # e.g. first session has no prior close
        ret = (self.data.Close[-1] - ref) / ref
        if ret > self.dir_min_move:
            return 1
        if ret < -self.dir_min_move:
            return -1
        return 0

    # ---- Pillar 2: strength gate. Return True only if trend is "strong enough".
    #      THIS is where your proprietary score plugs in. Replace the body with
    #      your own composite; keep it returning a bool (or a score + threshold). ----
    def _strong_enough(self) -> bool:
        if self.adx[-1] < self.adx_min:
            return False
        # distance of price from TODAY's open, in ATR units (intraday-only ref)
        ref = self.sess_open[-1]
        if not np.isfinite(ref):
            return False
        dist_atr = abs(self.data.Close[-1] - ref) / (self.atr[-1] + 1e-9)
        return dist_atr >= self.trend_dist_atr_min

    # ---- Pillar 3: was there a qualifying low-volume pullback that is now resuming? ----
    def _pullback_ok(self, direction: int) -> bool:
        n = self.pullback_lookback
        if len(self.data.Close) < max(n + 1, self.vol_lookback):
            return False

        window_high = float(np.max(self.data.High[-n:]))
        window_low = float(np.min(self.data.Low[-n:]))
        a = self.atr[-1] + 1e-9

        # retrace measured AGAINST the trend, in ATR units
        if direction == 1:
            retrace_atr = (window_high - self.data.Low[-1]) / a
            resuming = self.data.Close[-1] > self.data.Open[-1]  # last bar ticking back up
        else:
            retrace_atr = (self.data.High[-1] - window_low) / a
            resuming = self.data.Close[-1] < self.data.Open[-1]  # ticking back down

        size_ok = self.pullback_atr_min <= retrace_atr <= self.pullback_atr_max

        # low-volume condition: avg volume over the pullback window below baseline
        pull_vol = float(np.mean(self.data.Volume[-n:]))
        base_vol = self.vol_ma[-1]
        vol_ok = np.isfinite(base_vol) and pull_vol < self.pullback_vol_ratio * base_vol

        return bool(size_ok and vol_ok and resuming)

    # ---- Pillar 4: are we inside the allowed entry window? ----
    def _in_entry_window(self) -> bool:
        m = self.mso[-1]
        return self.entry_start_min <= m <= self.entry_end_min

    def next(self):
        price = self.data.Close[-1]
        a = self.atr[-1]
        if not np.isfinite(a) or a <= 0:
            return

        # Pillar 4 (exit side): force flat late in the window, no overnight risk
        if self.mso[-1] >= self.force_flat_min:
            if self.position:
                self.position.close()
            return

        # already in a trade -> let stop/target manage it (no pyramiding here)
        if self.position:
            return

        # Pillar 4 (entry side)
        if not self._in_entry_window():
            return

        # Pillar 1
        direction = self._trend_dir()
        if direction == 0:
            return

        # Pillar 2
        if not self._strong_enough():
            return

        # Pillar 3
        if not self._pullback_ok(direction):
            return

        # ---- size / risk. backtesting.py fills this MARKET order at NEXT bar open ----
        if direction == 1:
            sl = price - self.stop_atr * a
            tp = price + self.target_atr * a if self.target_atr else None
            self.buy(sl=sl, tp=tp)
        else:
            sl = price + self.stop_atr * a
            tp = price - self.target_atr * a if self.target_atr else None
            self.sell(sl=sl, tp=tp)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run(df: pd.DataFrame, cash: float = 100_000, commission: float = 0.0002,
        optimize: bool = False):
    """
    df: intraday OHLCV, RTH-only, capitalized columns, DatetimeIndex.
    commission: per-side fraction. 0.0002 = 2bps/side ~ retail-ish all-in.
                For honest intraday testing, set this DELIBERATELY high and
                re-check the edge (see pessimistic-fill note below).
    """
    bt = Backtest(
        df, TrendPullback,
        cash=cash,
        commission=commission,
        trade_on_close=False,     # MARKET orders fill at next bar OPEN (no lookahead)
        exclusive_orders=True,    # one position at a time
        finalize_trades=True,     # close any open trade at data end for full stats
    )

    if not optimize:
        stats = bt.run()
        return bt, stats

    stats = bt.optimize(
        adx_min=range(20, 41, 5),
        trend_dist_atr_min=[0.3, 0.5, 0.75, 1.0],
        pullback_atr_min=[0.3, 0.4, 0.5],
        pullback_vol_ratio=[0.7, 0.8, 0.9],
        stop_atr=[0.5, 0.75, 1.0, 1.5],
        target_atr=[1.5, 2.25, 3.0, 4.0],
        maximize="Sharpe Ratio",
        constraint=lambda p: p.pullback_atr_min < p.pullback_atr_max,
        max_tries=300,            # random subset — full grid is large
    )
    return bt, stats


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
RTH_START = "09:30"
RTH_END = "16:00"
MARKET_TZ = "America/New_York"


def _finalize(df: pd.DataFrame, tz: str = MARKET_TZ,
              rth_start: str = RTH_START, rth_end: str = RTH_END) -> pd.DataFrame:
    """Shared cleanup: capitalized OHLCV cols, tz-aware sorted index, RTH filter.
    Fails LOUD if required columns are missing rather than silently proceeding."""
    df = df.copy()

    # Flatten a possible MultiIndex on columns (yfinance does this for one ticker)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Normalize column names -> capitalized
    rename = {c: c.capitalize() for c in df.columns}
    df = df.rename(columns=rename)
    # handle 'Adj close' etc.
    df = df.rename(columns={"Adj close": "Adj Close", "Adj_close": "Adj Close"})

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Data is missing required columns {missing}. "
            f"Got columns: {list(df.columns)}"
        )
    df = df[required]

    # Index must be a sorted, tz-aware DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Data index must be a DatetimeIndex.")
    df = df.sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    else:
        df.index = df.index.tz_convert(tz)

    # Regular-session bars only
    df = df.between_time(rth_start, rth_end)

    # Drop any rows with NaNs in OHLCV (yfinance occasionally returns them)
    df = df.dropna(subset=required)
    if df.empty:
        raise ValueError("No rows left after cleaning/RTH filter — check the source.")
    return df


def load_yfinance(symbol: str = "SPY", period: str = "5d",
                  interval: str = "5m") -> pd.DataFrame:
    """Smoke-test loader. yfinance intraday limits (as of writing):
         1m  -> last ~7 days ;  2m/5m/15m/30m/60m -> last ~60 days.
    This is enough to prove the pipeline runs on REAL bars, NOT to validate edge."""
    try:
        import yfinance as yf
    except ImportError as e:
        raise ImportError(
            "yfinance not installed. Run: pip install yfinance"
        ) from e

    raw = yf.download(symbol, period=period, interval=interval,
                      auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise ValueError(
            f"yfinance returned no data for {symbol} (period={period}, "
            f"interval={interval}). Check the symbol / that markets were open."
        )
    return _finalize(raw)


def load_csv(path: str, ts_col: str = "timestamp") -> pd.DataFrame:
    """Load your own intraday CSV. Expects a timestamp column + OHLCV columns
    (any capitalization). Everything else is handled by _finalize()."""
    df = pd.read_csv(path)
    if ts_col not in df.columns:
        raise ValueError(
            f"Timestamp column '{ts_col}' not found. Columns: {list(df.columns)}. "
            f"Pass the right name via ts_col."
        )
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col)
    return _finalize(df)


def load_synthetic(days: int = 60, seed: int = 7) -> pd.DataFrame:
    """Deterministic fake RTH 5-min bars. Random-walk -> expect NO edge.
    Only proves the pipeline executes end-to-end without lookahead errors."""
    rng = np.random.default_rng(seed)
    bdays = pd.bdate_range("2024-01-02", periods=days)
    rows = []
    for d in bdays:
        bars = pd.date_range(d + pd.Timedelta("9:30:00"),
                             d + pd.Timedelta("16:00:00"), freq="5min")
        drift = rng.normal(0, 0.0004)
        px = 100 * np.exp(np.cumsum(rng.normal(drift, 0.0009, len(bars))))
        vol = rng.integers(500, 5000, len(bars))
        o = px * (1 + rng.normal(0, 0.0002, len(bars)))
        h = np.maximum(o, px) * (1 + abs(rng.normal(0, 0.0003, len(bars))))
        lo = np.minimum(o, px) * (1 - abs(rng.normal(0, 0.0003, len(bars))))
        for t, oo, hh, ll, cc, vv in zip(bars, o, h, lo, px, vol):
            rows.append((t, oo, hh, ll, cc, vv))
    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"]
                      ).set_index("ts")
    return _finalize(df)


def load_data(source: str = "synthetic", **kwargs) -> pd.DataFrame:
    """One entry point. source in {'synthetic', 'yfinance', 'csv'}."""
    if source == "synthetic":
        return load_synthetic(**kwargs)
    if source == "yfinance":
        return load_yfinance(**kwargs)
    if source == "csv":
        return load_csv(**kwargs)
    raise ValueError(f"Unknown source '{source}'. Use synthetic | yfinance | csv.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Intraday trend-pullback backtest.")
    p.add_argument("--source", default="synthetic",
                   choices=["synthetic", "yfinance", "csv", "polygon"])
    p.add_argument("--symbol", default="SPY",
                   help="ticker (yfinance or polygon source)")
    p.add_argument("--period", default="5d", help="yfinance period, e.g. 5d, 60d")
    p.add_argument("--interval", default="5m",
                   help="yfinance interval: 1m (~7d), 5m/15m/30m/60m (~60d)")
    p.add_argument("--csv", help="path to CSV when --source csv")
    p.add_argument("--ts-col", default="timestamp", help="timestamp column in CSV")
    # polygon-specific
    p.add_argument("--start", help="YYYY-MM-DD (polygon source)")
    p.add_argument("--end", help="YYYY-MM-DD (polygon source; default today)")
    p.add_argument("--lookback-days", type=int, default=30,
                   help="polygon: days back from today if --start omitted")
    p.add_argument("--multiplier", type=int, default=5,
                   help="polygon bar multiplier (e.g. 5 with minute = 5-min bars)")
    p.add_argument("--timespan", default="minute",
                   choices=["minute", "hour", "day"], help="polygon bar timespan")
    p.add_argument("--commission", type=float, default=0.0002,
                   help="per-side fraction; raise this for honest cost testing")
    p.add_argument("--plot", action="store_true", help="open interactive chart")
    args = p.parse_args()

    if args.source == "yfinance":
        df = load_data("yfinance", symbol=args.symbol,
                       period=args.period, interval=args.interval)
        print(f"Loaded {len(df)} {args.interval} RTH bars for {args.symbol} "
              f"({df.index[0]} -> {df.index[-1]})")
    elif args.source == "csv":
        if not args.csv:
            p.error("--source csv requires --csv PATH")
        df = load_data("csv", path=args.csv, ts_col=args.ts_col)
        print(f"Loaded {len(df)} RTH bars from {args.csv}")
    elif args.source == "polygon":
        try:
            from polygon_data import fetch_bars
        except ImportError:
            p.error("--source polygon needs polygon_data.py in the same folder.")
        df = fetch_bars(
            args.symbol,
            start=args.start or (
                (datetime.now() - timedelta(days=args.lookback_days))
                .strftime("%Y-%m-%d")),
            end=args.end or datetime.now().strftime("%Y-%m-%d"),
            multiplier=args.multiplier,
            timespan=args.timespan,
        )
        print(f"Loaded {len(df)} {args.multiplier}{args.timespan} RTH bars for "
              f"{args.symbol} ({df.index[0]} -> {df.index[-1]})")
    else:
        df = load_data("synthetic")
        print(f"Loaded {len(df)} synthetic RTH bars")

    bt, stats = run(df, commission=args.commission)
    print(stats)

    n_trades = stats["# Trades"]
    print("\n--- interpretation ---")
    if args.source == "synthetic":
        print("Random-walk data -> any edge shown is noise. Pipeline-only check.")
    elif n_trades < 20:
        print(f"Only {n_trades} trades — this is a SMOKE TEST, not evidence of edge. "
              "A few days of bars can't validate anything; it confirms the strategy "
              "fires on real market data with real timestamps/volume.")
    else:
        print(f"{n_trades} trades on real bars. Still a smoke test over a short "
              "window — treat stats as directional only, and re-run with higher "
              "--commission to see how fast the edge decays under realistic costs.")

    if args.plot:
        bt.plot()