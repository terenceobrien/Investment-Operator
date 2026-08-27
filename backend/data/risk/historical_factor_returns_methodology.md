# Historical Factor Returns Methodology

## Production Reuse

Factor returns are built by importing and calling `build_factor_returns()` from
`risk/factor_model.py`. No factor transformation is
reimplemented in this research script. Complete-model production differences:
**none**. Earlier partial-history rows are a research-only extension and are null
for factors whose required inputs are not yet available.

Prices are yfinance daily `Close` values requested with `auto_adjust=True`, matching
the production factor runner. Missing prices are not forward-filled.

The exported return panel uses the union of factor histories. MKT begins with SPY.
AI begins when SPY, SOXX, QQQ, and RSP returns are all available. Each style factor
begins when its ETF return plus MKT and AI are available. Partial-history factors use
the production `_residualize()` function over their maximal valid dependency window.
On and after the complete-model overlap, values are replaced with the exact output
of production `build_factor_returns()`, preserving production numerical parity.

## ETF Mapping

| Factor | ETF |
|---|---|
| MKT | SPY |
| MOM | MTUM |
| QUAL | QUAL |
| VAL | IWD |
| SIZE | IWM |
| LOWVOL | USMV |

AI raw spread: `{'SOXX': 0.5, 'QQQ': 0.5}` long and `{'RSP': 1.0}` short. AI is residualized against
MKT. MOM, QUAL, VAL, SIZE, and LOWVOL are then residualized against `[MKT, AI]`,
with the ordering and intercept behavior defined exclusively by production code.

## Coverage

| Ticker | First adjusted price |
|---|---|
| IWD | 2000-05-26 |
| IWM | 2000-05-26 |
| MTUM | 2013-04-18 |
| QQQ | 1999-03-10 |
| QUAL | 2013-07-18 |
| RSP | 2003-05-01 |
| SOXX | 2001-07-13 |
| SPY | 1993-01-29 |
| USMV | 2011-10-20 |

- First date with all required ETF prices: 2013-07-18
- First date with any factor return: 1993-02-01
- First complete production-factor date: 2013-07-19
- Last factor-return date: 2026-08-21
- Factor observations: 8,447

| Factor | First available return |
|---|---|
| MKT | 1993-02-01 |
| AI | 2003-05-02 |
| MOM | 2013-04-19 |
| QUAL | 2013-07-19 |
| VAL | 2003-05-02 |
| SIZE | 2003-05-02 |
| LOWVOL | 2011-10-21 |

## Hedge Episodes

- Canonical source: `/Users/terenceobrien/AI_Financial_Operator/backend/data/risk/hedge_drawdown_episodes_25.csv`
- Episode count: 25 (strictly required to equal 25)
- Complete seven-factor ±window coverage: 9
- Episodes without complete coverage: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
- Daily mapping window: 60 factor trading observations before peak through 20
  factor trading observations after trough.
- The episode table is reused as supplied. This script does not define, optimize,
  or independently regenerate drawdown episodes.

## QA

- MKT max absolute error versus aligned SPY log return: 0.000e+00
- Complete-window max absolute error versus production: 0.000e+00
- Maximum absolute residual factor beta: 4.577e-16
- Factor columns: MKT, AI, MOM, QUAL, VAL, SIZE, LOWVOL

This pass performs data preparation only. It computes no conditional factor shock,
quantile, crash average, regime classification, or replacement production stress vector.
