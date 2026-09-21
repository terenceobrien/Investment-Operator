# Daily portfolio ledger

Run from the project root:

```bash
python3 scripts/build_master_portfolio.py
```

Override the inputs or output location:

```bash
python3 scripts/build_master_portfolio.py \
  --transactions "$HOME/Downloads/Full Account History.csv" \
  --prices prices.csv \
  --output-dir data/portfolio
```

Dependencies: `pandas`, `numpy`, `scipy`, `pandas_market_calendars`. No prices or other
information are fetched from the network. The script supports this inspected
Fidelity schema; unfamiliar actions are retained for review, not guessed.
The original input files are not modified.

## Files

- `master_portfolio_daily.csv`: one row for each supplied price date on or after
  the first transaction; includes cash, quantities, per-instrument values,
  portfolio totals, flows, returns, and quality flags.
- `portfolio_reconciliation_issues.csv`: dated issues, ticker and input row
  references when available, and review details.
- `normalized_transactions.csv`: audit trail with original signed amounts,
  quantities, categories, effective/ledger dates, cash adjustments, and fees.
  `Source_Row` is the original CSV line number including its header.
- `current_positions.csv`: nonzero positions at the final price date.
- `master_option_daily.csv`: one row per active/event date and option contract,
  including zero-quantity closing dates; observed premiums, model estimates,
  IVs, underlying prices, quantity, and method are separately auditable.
- `option_position_ledger.csv`: one row per opening lot, with fixed entry IV,
  remaining quantity, closing details, and after-fee net cash P&L for completed lots.
- `option_reconciliation_report.txt`: every completed lot's reconciliation,
  model/fallback counts, and the full BABA entry-through-exit path.
- `reconciliation_report.txt`: totals, checks, and the current-position summary.

## Accounting conventions

All amounts are USD, as implied by the Fidelity dollar-denominated fields. The
script rejects mixed accounts. The first transaction establishes presumed
inception with zero prior cash and positions. This is a full-history reconstruction,
not an independently verified brokerage statement. An incomplete source history
can still produce internally consistent balances.

**Trade dates and cash.** Buys/sells affect quantities and economic cash on `Run
Date`, not settlement date. Cash therefore includes unsettled trade payables and
receivables as well as core cash; it is not Fidelity's settled-cash/withdrawal-
available balance. A negative value can represent margin borrowing and is flagged
for review. Signed `Amount ($)` is authoritative and already includes trade fees.
The script accumulates money in integer cents and quantities with `Decimal`,
converting quantities to floating point only for valuation and output. No share
quantities are deliberately rounded. A tolerance is used only for diagnostics.

**External flows.** Only explicit, directionally consistent EFT/bank wire receipt
or payment records without security quantities are automatically classified as
external. Positive is a deposit; negative is a withdrawal. Generic transfers,
journals, distributions with unclear meaning, corporate actions, and unknown
actions require review. Unknown signed cash amounts remain visible in the cash
ledger, but returns become ineligible from the affected date. Unknown security
quantity changes are not silently interpreted as buys or sells.

**Core cash.** `CORE_SYMBOLS = {"SPAXX"}` is configured near the top of the script.
SPAXX is included in Cash, not in the security quantity/MV columns. Dividends
increase cash once. A matching $1 SPAXX purchase/reinvestment/redemption is just a
change in cash representation, so its posted cash amount is excluded from economic
cash and its quantity is not added as a second asset. Core trades that do not
match the expected $1 relationship are flagged. The observed $55.32 of reinvestment
debits are reversed by `Core_Bookkeeping_Adjustment`. This does not add new income;
the original dividend credits already recognize it. Full SPAXX unit ownership
cannot be inferred from dividend reinvestments alone.

**Cash/margin journals.** Paired `AUTO-JOURNAL` rows net to zero by date and ticker.
They move custody between subaccount types, not into/out of the portfolio.
Unbalanced pairs invalidate the ledger pending review.

**Dividends.** Stock/ETF and core dividends enter cash on the recorded payment date
and are internal returns. Non-core reinvestments are share purchases funded by
cash. Dividend receivables are not accrued on ex-dividend dates. Prices use `Close`
only, never `Adj Close`. Corporate actions other than these explicit reinvestments
are flagged for manual review. Confirm the supplied Close series has the correct
historical share basis if the account later includes splits or reorganizations.

**Calendar.** The master uses the union of dates in the supplied price file. The
NYSE calendar checks missing whole sessions and unexpected non-session dates; it
does not invent price rows. Nontrading-date activity is carried to the next
available price date and documented. Transactions after the final price date are
reported and excluded from the master until prices are extended. Prices beyond
the latest transaction posting require review of the history export's coverage.
The script assumes supplied daily Close observations are finalized EOD prices;
the CSV alone cannot verify whether its latest row was downloaded intraday.

**Missing prices.** No price forward fills. A missing Close while held leaves that
instrument's MV, the securities total, and Total_NAV blank. Missing prices for
zero positions do not affect NAV. Prices have unique Date/Ticker keys; invalid
numbers and duplicate keys fail explicitly. Blank price cells are retained as
missing and flagged if held.

## Options and estimated marks

The pricing code is in `scripts/portfolio_option_valuation.py`. It uses direct
Black-Scholes-Merton equations with SciPy's normal CDF and `brentq` solver; no
options-pricing package, quote service, or future exit prices are used.

Configure the continuous annual risk-free rate and dividend assumptions near the
top of `scripts/build_master_portfolio.py`, or with CLI options:

```bash
python3 scripts/build_master_portfolio.py --risk-free-rate 0.04 \
  --dividend-yield 0.0 --dividend-yield-for XYZ=0.015
```

`0.04` means 4%, not `4`. `DIVIDEND_YIELDS` supports underlying-specific defaults.
The numerical functions accept rates explicitly so a later date-dependent rate
provider does not require changing the BSM equations. No historical yield database
is built. For each lot, IV is solved once from its entry premium, underlying Close
on its effective entry date, literal Fidelity strike, expiry, r, and q. Remaining
calendar days / 365 determines time to expiry. The IV solver enforces intrinsic
and discounted BSM bounds and brackets volatility between 0.0001 and 5.0. A
failure generates a warning in the reconciliation issues and triggers fallback.

### Valuation hierarchy

1. On dates with observed transactions, use the actual premium per share. Fees
   remain cash expenses, not an extra part of the option asset. Missing premium
   fields can be recovered from gross transaction cash (net Amount plus fees).
2. Otherwise, value each remaining opening lot with its original entry IV, that
   day's underlying Close, and the remaining time to expiry. Adding a new lot does
   not recalibrate older lots. Aggregate the lot values, not their implied vols.
3. If a lot cannot be modeled, carry the most recent observed price for the same
   contract, falling back to the known entry premium. An invalid strike/expiry,
   missing spot, or impossible IV does not create a NaN option value. If both a
   premium and recoverable entry cash are absent, the source data are insufficient
   and the script fails explicitly rather than inventing a mark.
4. Explicit closing/expiration/exercise records control quantities and cash.
   Option MV is zero after fully closing, even though its actual closing premium
   is retained in the option audit. Sale proceeds are already in Cash; including
   an additional option asset after exit would double-count them.

The date-only Fidelity export has no execution timestamps. Within a date,
explicit openings are processed before explicit closings, preserving source-row
order within each group. When multiple executions exist, the quote used for EOD
is the quantity-weighted mean of that date's closing fills, if present, otherwise
its opening fills. This is an observed-price proxy for EOD, not an assertion that
it was the exchange closing quote. FIFO matches partial closes to opening lots
for model tracking and cash reconciliation, not tax cost-basis reporting. An
ambiguous opposing opening or unmatched closing is flagged for review.

Original Fidelity symbols remain in portfolio columns, e.g. `QTY_-BABA260807C120`.
The separate option audit uses `BABA_2026-08-07_C_120`. Fidelity's strike suffix
`120` is literal dollars, not the OCC strike scaling convention. A description
parser supplies missing contract metadata where possible. The contract multiplier
comes from `(100 SHS)` or another explicit share count, defaulting to 100.
Quantities are signed contracts: shorts have negative option market values.

For multiple open lots with different IVs, aggregate `Entry_IV` is blank and
`Entry_IVs` enumerates them; the individual lot IVs are in the position ledger.
`Estimated_Option_Price` is the remaining-contract-weighted modeled premium;
`Actual_Option_Price` is populated only on observed transaction dates. `Price_Used`
is the selected per-share mark and `Option_Market_Value` is the signed quantity
multiplied by its multiplier and mark. `Valuation_Method` identifies the hierarchy
branch. A `mixed` value means different lot methods were required.

### Expiration, exercise and accounting

Explicit expiration records close contracts using their signed quantities on the
stated `as of` date, cross-checked against a known contract expiry. The two IWM
expirations here were posted the following day but effective on the preceding day.
For a still-open contract at expiry, an available underlying Close supplies an
intrinsic mark. The quantity is **not** silently erased: an unresolved expired
position still blocks trusted returns pending an actual closing/settlement record.

Exercise/assignment records use actual option cash and underlying share delivery
records. A strike shown on an exercise record is not mistaken for an option
premium. No synthetic sale proceeds or underlying shares are created. A zero-cash
option exercise without a corresponding stock leg is flagged. Option-only cash
P&L on exercise excludes economics that have moved into the underlying shares.

The existing `Option_Net_Cash_Flow` and `Option_Realized_Cash_Flow` calculations are
unchanged. The former records daily net option cash; the latter recognizes each
fully closed contract episode's accumulated net cash on its flat date. Completed
opening-lot reconciliations separately allocate actual cash across partial closes.
All reported realized option results include recorded commissions and fees.

A $400 premium purchase creates a $400 option asset and reduces cash by $400;
only fees reduce entry NAV. Modeling changes subsequent marks, not capital flows,
quantities, or actual closing cash economics.

### Limitations

US listed equity options are generally American-style, while BSM is a European
model. Constant entry IV ignores changing implied volatility; historical spreads,
early-exercise premiums, and discrete dividends are not reconstructed. Combining
an intraday premium with an EOD underlying price can make entry IV unsolvable,
especially for expiry-day trades. Actual intraday round trips can still reconcile
without an IV or any overnight modeled mark. These marks support continuous NAV
and estimated return/drawdown/volatility analytics, not exact brokerage valuations.
They may still jump when a new actual transaction replaces a modeled or carried
price. No exit price or future lot is used to smooth earlier marks.

### BABA reconstruction using r=0.04 and q=0

The July 9 $2.73 entry premium implies IV **46.6648%** for the August 7 $120 call.
The six-date path, including the final exit date, is:

| Date | Premium used per share | EOD option value | Method |
|---|---:|---:|---|
| 2026-07-09 | 2.730000 | 273.00 | Actual entry |
| 2026-07-10 | 3.019492 | 301.95 | Constant-entry-IV BSM |
| 2026-07-13 | 2.725064 | 272.51 | Constant-entry-IV BSM |
| 2026-07-14 | 2.612428 | 261.24 | Constant-entry-IV BSM |
| 2026-07-15 | 4.597350 | 459.73 | Constant-entry-IV BSM |
| 2026-07-16 | 5.000000 | 0.00 | Actual exit; proceeds in cash |

The exit premium exceeds the preceding model by $0.402650 per share, or $40.2650
for one standard contract, before closing fees. Actual net cash profit remains
$225.66. All five formerly missing option NAVs are now populated (one observed
entry mark and four modeled intermediate marks). The option report prints this
path on every run from the actual inputs; this example reflects the current files.

## Returns with estimated option marks

Daily returns follow the requested end-of-day-flow convention:

```text
Daily_Return[t] = (Total_NAV[t] - External_Flow[t]) / Total_NAV[t-1] - 1
Cumulative_Return[t] = product(1 + Daily_Return[1:t]) - 1
```

Returns are decimal fractions (`0.01` means 1%). The first daily return is blank
and its cumulative base is zero if the initial NAV is valid and positive. This
convention does not measure performance before that first EOD valuation.
Both adjacent valuations must be complete and trusted, and the prior NAV must be
positive. Daily returns can resume after two consecutive complete valuations.
Cumulative return never skips missing returns or restarts its inception base.
Model/fallback option marks are eligible for returns and explicitly labeled;
a remaining stock-price or transaction-reconciliation gap still interrupts them.
No benchmark returns are added: SPY appears only as an actually owned security
and as an option underlying.

## Diagnostics

- `Buy_Cash_Flow` / `Sell_Cash_Flow`: signed stock/ETF trade cash before separately
  reported fees. Option trade flows have separate corresponding columns.
- `Fees`: signed expense, negative for fees paid, including trading commissions.
- `Net_Internal_Cash_Flow`: all cash movement other than external capital; equals
  gross stock/option trade flows + dividends + interest + fees + other internal
  cash activity. Do not add `Option_Net_Cash_Flow` again; it is an overlapping
  diagnostic already represented in the option gross flows and fees.
- `Raw_Transaction_Cash_Flow + Core_Bookkeeping_Adjustment = Net_Cash_Flow`.
- `Cash_Reconciliation_Residual`: difference between actual reconstructed cash
  movement and external plus internal flows; required to be zero.
- `Position_Count`: number of nonzero securities plus option contracts, excluding
  core cash; separate stock and option counts are provided.
- `Known_Assets_Subtotal`: cash plus securities value, before options. This is not
  a complete NAV when options are open.
- `Option_Valuation_Method`: `none` when no option is open; otherwise the EOD
  active-contract method or `mixed`.
- `Option_MV_Estimated_Flag`: an open option uses a modeled, intrinsic, or carried
  mark rather than a same-date actual execution. Estimated does not mean missing.
- `Option_Pricing_Incomplete_Flag`: a numeric option value is unavailable after
  the hierarchy, not simply that exchange quotes are absent. Model/fallback marks
  do not set this flag or disqualify the date's returns.
- `NAV_Incomplete_Flag`: a required stock or option value remains unavailable.
- `Ledger_Reconciliation_Incomplete_Flag`: unresolved interpretation/coverage or
  quantity issues that invalidate the ledger from the event onward.
- `NAV_Potentially_Incomplete_Flag`: either of the preceding limitations.
- `Return_Eligible_Flag`: this date's NAV is usable; the adjacent prior date must
  also be usable for an actual daily return.
- `Cumulative_Return_Incomplete_Flag`: inception compounding is unavailable.
- `Invalidates_Ledger_From_Date` in the issues file denotes persistent ledger
  interpretation problems. Option model/fallback warnings are nonblocking; their methods and assumptions
  remain visible in the option audit. Unresolved stock-price gaps still set the
  daily price/NAV flags.

Current quantities are checked both against classified deltas and the original
signed quantities (including offsetting journals), and against the full history
when its dates exceed price coverage. Tiny nonzero residuals after apparent exits
are flagged rather than rounded away. The current summary reconciles to the last
row's component market values. An actual Fidelity position/cash snapshot would
provide the independent final reconciliation that these two inputs cannot.

Run the offline accounting tests:

```bash
python3 -m pytest tests/test_master_portfolio.py tests/test_portfolio_option_valuation.py -q
```
