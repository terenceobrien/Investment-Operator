# Sharadar S&P 500 Membership QA

Generated: `2026-08-15T01:04:15.090313+00:00`
Script version: `2026-08-14.1`

## Methodology
Historical rows are authoritative anchor snapshots on their own dates. Between anchors, only added/removed events effective through each date are replayed. At the next historical snapshot, replayed state is compared to the snapshot for QA and then reset to the snapshot. Current rows are used only as a latest-state validation anchor.

## Event-Date Semantics
Added tickers are members on event date D; removed tickers are not members on event date D. For non-trading event dates, the next trading session reflects all events effective through that date. If an event shares a historical snapshot date, the snapshot is authoritative for that anchor date.

## Snapshot Summary
- `distinct_historical_snapshot_dates`: 114
- `first_snapshot_date`: 1998-03-31
- `last_snapshot_date`: 2026-06-30
- `min_snapshot_member_count`: 500
- `max_snapshot_member_count`: 505
- `mean_snapshot_member_count`: 501.70175438596493
- `median_snapshot_member_count`: 500.0
- `snapshot_frequency_found`: quarterly historical snapshots from 1998-03-31 through 2026-06-30
- `current_constituent_count`: 503
- `current_date`: 2026-08-13
- `historical_snapshot_count_by_date`: [{'date': '1998-03-31', 'member_count': 500}, {'date': '1998-06-30', 'member_count': 500}, {'date': '1998-09-30', 'member_count': 500}, {'date': '1998-12-31', 'member_count': 500}, {'date': '1999-03-31', 'member_count': 500}, {'date': '1999-06-30', 'member_count': 500}, {'date': '1999-09-30', 'member_count': 500}, {'date': '1999-12-31', 'member_count': 500}, {'date': '2000-03-31', 'member_count': 500}, {'date': '2000-06-30', 'member_count': 500}, {'date': '2000-09-30', 'member_count': 500}, {'date': '2000-12-31', 'member_count': 500}, {'date': '2001-03-31', 'member_count': 500}, {'date': '2001-06-30', 'member_count': 500}, {'date': '2001-09-30', 'member_count': 500}, {'date': '2001-12-31', 'member_count': 500}, {'date': '2002-03-31', 'member_count': 500}, {'date': '2002-06-30', 'member_count': 500}, {'date': '2002-09-30', 'member_count': 500}, {'date': '2002-12-31', 'member_count': 500}, {'date': '2003-03-31', 'member_count': 500}, {'date': '2003-06-30', 'member_count': 500}, {'date': '2003-09-30', 'member_count': 500}, {'date': '2003-12-31', 'member_count': 500}, {'date': '2004-03-31', 'member_count': 500}, {'date': '2004-06-30', 'member_count': 500}, {'date': '2004-09-30', 'member_count': 500}, {'date': '2004-12-31', 'member_count': 500}, {'date': '2005-03-31', 'member_count': 500}, {'date': '2005-06-30', 'member_count': 500}, {'date': '2005-09-30', 'member_count': 500}, {'date': '2005-12-31', 'member_count': 500}, {'date': '2006-03-31', 'member_count': 500}, {'date': '2006-06-30', 'member_count': 500}, {'date': '2006-09-30', 'member_count': 500}, {'date': '2006-12-31', 'member_count': 500}, {'date': '2007-03-31', 'member_count': 500}, {'date': '2007-06-30', 'member_count': 500}, {'date': '2007-09-30', 'member_count': 500}, {'date': '2007-12-31', 'member_count': 500}, {'date': '2008-03-31', 'member_count': 500}, {'date': '2008-06-30', 'member_count': 500}, {'date': '2008-09-30', 'member_count': 500}, {'date': '2008-12-31', 'member_count': 500}, {'date': '2009-03-31', 'member_count': 500}, {'date': '2009-06-30', 'member_count': 500}, {'date': '2009-09-30', 'member_count': 500}, {'date': '2009-12-31', 'member_count': 500}, {'date': '2010-03-31', 'member_count': 500}, {'date': '2010-06-30', 'member_count': 500}, {'date': '2010-09-30', 'member_count': 500}, {'date': '2010-12-31', 'member_count': 500}, {'date': '2011-03-31', 'member_count': 500}, {'date': '2011-06-30', 'member_count': 500}, {'date': '2011-09-30', 'member_count': 500}, {'date': '2011-12-31', 'member_count': 500}, {'date': '2012-03-31', 'member_count': 500}, {'date': '2012-06-30', 'member_count': 500}, {'date': '2012-09-30', 'member_count': 500}, {'date': '2012-12-31', 'member_count': 500}, {'date': '2013-03-31', 'member_count': 500}, {'date': '2013-06-30', 'member_count': 500}, {'date': '2013-09-30', 'member_count': 500}, {'date': '2013-12-31', 'member_count': 500}, {'date': '2014-03-31', 'member_count': 500}, {'date': '2014-06-30', 'member_count': 501}, {'date': '2014-09-30', 'member_count': 502}, {'date': '2014-12-31', 'member_count': 502}, {'date': '2015-03-31', 'member_count': 502}, {'date': '2015-06-30', 'member_count': 502}, {'date': '2015-09-30', 'member_count': 505}, {'date': '2015-12-31', 'member_count': 504}, {'date': '2016-03-31', 'member_count': 504}, {'date': '2016-06-30', 'member_count': 505}, {'date': '2016-09-30', 'member_count': 505}, {'date': '2016-12-31', 'member_count': 505}, {'date': '2017-03-31', 'member_count': 505}, {'date': '2017-06-30', 'member_count': 505}, {'date': '2017-09-30', 'member_count': 505}, {'date': '2017-12-31', 'member_count': 505}, {'date': '2018-03-31', 'member_count': 505}, {'date': '2018-06-30', 'member_count': 505}, {'date': '2018-09-30', 'member_count': 505}, {'date': '2018-12-31', 'member_count': 505}, {'date': '2019-03-31', 'member_count': 505}, {'date': '2019-06-30', 'member_count': 505}, {'date': '2019-09-30', 'member_count': 505}, {'date': '2019-12-31', 'member_count': 505}, {'date': '2020-03-31', 'member_count': 505}, {'date': '2020-06-30', 'member_count': 505}, {'date': '2020-09-30', 'member_count': 505}, {'date': '2020-12-31', 'member_count': 505}, {'date': '2021-03-31', 'member_count': 505}, {'date': '2021-06-30', 'member_count': 505}, {'date': '2021-09-30', 'member_count': 505}, {'date': '2021-12-31', 'member_count': 505}, {'date': '2022-03-31', 'member_count': 505}, {'date': '2022-06-30', 'member_count': 503}, {'date': '2022-09-30', 'member_count': 503}, {'date': '2022-12-31', 'member_count': 503}, {'date': '2023-03-31', 'member_count': 503}, {'date': '2023-06-30', 'member_count': 503}, {'date': '2023-09-30', 'member_count': 503}, {'date': '2023-12-31', 'member_count': 503}, {'date': '2024-03-31', 'member_count': 503}, {'date': '2024-06-30', 'member_count': 503}, {'date': '2024-09-30', 'member_count': 504}, {'date': '2024-12-31', 'member_count': 503}, {'date': '2025-03-31', 'member_count': 503}, {'date': '2025-06-30', 'member_count': 503}, {'date': '2025-09-30', 'member_count': 503}, {'date': '2025-12-31', 'member_count': 503}, {'date': '2026-03-31', 'member_count': 503}, {'date': '2026-06-30', 'member_count': 503}]

## Action Counts
- `added`: 1236
- `removed`: 739
- `historical`: 57194
- `current`: 503

## Daily Membership Count Stats
- `trading_dates`: 7137
- `first_date`: 1998-03-31
- `last_date`: 2026-08-13
- `min_member_count`: 499
- `max_member_count`: 507
- `mean_member_count`: 501.69609079445144
- `median_member_count`: 500.0

## Snapshot Reconciliation
| snapshot_date | snapshot_count | replayed_count_before_reset | missing_from_replay_count | extra_in_replay_count | missing_from_replay_examples | extra_in_replay_examples | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1998-03-31 | 500 | None | 0 | 0 | [] | [] | first historical snapshot anchor |
| 1998-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 1998-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 1998-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 1999-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 1999-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 1999-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 1999-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2000-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2000-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2000-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2000-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2001-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2001-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2001-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2001-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2002-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2002-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2002-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2002-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2003-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2003-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2003-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2003-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2004-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2004-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2004-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2004-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2005-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2005-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2005-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2005-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2006-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2006-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2006-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2006-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2007-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2007-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2007-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2007-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2008-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2008-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2008-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2008-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2009-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2009-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2009-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2009-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2010-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2010-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2010-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2010-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2011-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2011-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2011-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2011-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2012-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2012-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2012-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2012-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2013-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2013-06-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2013-09-30 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2013-12-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2014-03-31 | 500 | 500 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2014-06-30 | 501 | 501 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2014-09-30 | 502 | 502 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2014-12-31 | 502 | 502 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2015-03-31 | 502 | 502 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2015-06-30 | 502 | 502 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2015-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2015-12-31 | 504 | 504 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2016-03-31 | 504 | 504 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2016-06-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2016-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2016-12-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2017-03-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2017-06-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2017-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2017-12-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2018-03-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2018-06-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2018-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2018-12-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2019-03-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2019-06-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2019-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2019-12-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2020-03-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2020-06-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2020-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2020-12-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2021-03-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2021-06-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2021-09-30 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2021-12-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2022-03-31 | 505 | 505 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2022-06-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2022-09-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2022-12-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2023-03-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2023-06-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2023-09-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2023-12-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2024-03-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2024-06-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2024-09-30 | 504 | 504 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2024-12-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2025-03-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2025-06-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2025-09-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2025-12-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2026-03-31 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |
| 2026-06-30 | 503 | 503 | 0 | 0 | [] | [] | state reset to historical snapshot after comparison |

## Current Reconciliation
- `current_date`: 2026-08-13
- `current_count`: 503
- `replayed_count`: 503
- `missing_from_replay_count`: 0
- `extra_in_replay_count`: 0
- `missing_from_replay_examples`: []
- `extra_in_replay_examples`: []
- `note`: current rows are validation only; they are not used to rewrite historical membership

## Price Coverage
- `first_reliable_sep_coverage_date`: 1997-12-31
- `first_date_with_95pct_price_coverage`: 1998-03-31
- `first_date_with_99pct_price_coverage`: 1998-03-31

### Coverage Stats
- `first_date`: 1998-03-31
- `last_date`: 2026-08-13
- `min_coverage_pct`: 99.60159362549801
- `mean_coverage_pct`: 99.99447478182812
- `median_coverage_pct`: 100.0
- `min_missing_members`: 0
- `max_missing_members`: 2
- `mean_missing_members`: 0.027742749054224466

### High Missing-Price Dates
_None._

### Missing Ticker Examples
| ticker | missing_dates | first_missing_date | last_missing_date |
| --- | --- | --- | --- |
| CCE1 | 58 | 1998-10-08 | 1998-12-30 |
| NBL | 5 | 2020-10-05 | 2020-10-09 |
| AGN1 | 4 | 2015-03-17 | 2015-03-20 |
| COL | 4 | 2018-11-27 | 2018-11-30 |
| JNPR | 4 | 2025-07-02 | 2025-07-08 |
| RHT | 4 | 2019-07-09 | 2019-07-12 |
| SUN1 | 4 | 2012-10-04 | 2012-10-09 |
| ATVI | 3 | 2023-10-13 | 2023-10-17 |
| CTLT | 3 | 2024-12-18 | 2024-12-20 |
| DAY | 3 | 2026-02-04 | 2026-02-06 |
| HAR | 3 | 2017-03-13 | 2017-03-15 |
| POM1 | 3 | 2016-03-24 | 2016-03-29 |
| PXD | 3 | 2024-05-03 | 2024-05-07 |
| SPLS1 | 3 | 2017-09-13 | 2017-09-15 |
| TOS1 | 3 | 2001-09-17 | 2001-09-19 |
| TSS | 3 | 2019-09-18 | 2019-09-20 |
| VAR | 3 | 2021-04-15 | 2021-04-19 |
| AET | 2 | 2018-11-29 | 2018-11-30 |
| AFS.A | 2 | 2000-12-01 | 2000-12-04 |
| BCR | 2 | 2017-12-29 | 2018-01-02 |
| BHI | 2 | 2017-07-05 | 2017-07-06 |
| CXO | 2 | 2021-01-19 | 2021-01-20 |
| DTV1 | 2 | 2015-07-27 | 2015-07-28 |
| ETFC | 2 | 2020-10-05 | 2020-10-06 |
| FDC1 | 2 | 2007-09-24 | 2007-09-25 |
| GMCR | 2 | 2016-03-03 | 2016-03-04 |
| HES | 2 | 2025-07-21 | 2025-07-22 |
| HOLX | 2 | 2026-04-07 | 2026-04-08 |
| INFO1 | 2 | 2022-02-28 | 2022-03-01 |
| JAVA1 | 2 | 2010-01-27 | 2010-01-28 |
| MRO | 2 | 2024-11-22 | 2024-11-25 |
| NFX1 | 2 | 2019-02-13 | 2019-02-14 |
| TWTR | 2 | 2022-10-28 | 2022-10-31 |
| TWX | 2 | 2018-06-18 | 2018-06-19 |
| WCG | 2 | 2020-01-24 | 2020-01-27 |
| XL1 | 2 | 2018-09-12 | 2018-09-13 |
| ADT1 | 1 | 2016-05-02 | 2016-05-02 |
| AGC1 | 1 | 2001-08-29 | 2001-08-29 |
| AGN | 1 | 2020-05-11 | 2020-05-11 |
| ALTR1 | 1 | 2015-12-28 | 2015-12-28 |
| AT1 | 1 | 2007-11-16 | 2007-11-16 |
| AWE | 1 | 2001-07-06 | 2001-07-06 |
| BLS | 1 | 2007-01-03 | 2007-01-03 |
| BUD1 | 1 | 2008-11-18 | 2008-11-18 |
| CB1 | 1 | 2016-01-15 | 2016-01-15 |
| CCU1 | 1 | 2008-07-30 | 2008-07-30 |
| CFL1 | 1 | 1998-04-28 | 1998-04-28 |
| CFN | 1 | 2015-03-17 | 2015-03-17 |
| COC | 1 | 2002-09-03 | 2002-09-03 |
| CPGX | 1 | 2016-07-01 | 2016-07-01 |
| CTXS | 1 | 2022-09-30 | 2022-09-30 |
| CVC | 1 | 2016-06-21 | 2016-06-21 |
| CVH | 1 | 2013-05-07 | 2013-05-07 |
| DI1 | 1 | 1998-09-30 | 1998-09-30 |
| EDS | 1 | 2008-08-26 | 2008-08-26 |
| EMC1 | 1 | 2016-09-07 | 2016-09-07 |
| ESRX | 1 | 2018-12-21 | 2018-12-21 |
| FDO | 1 | 2015-07-07 | 2015-07-07 |
| FTI | 1 | 2017-01-13 | 2017-01-13 |
| G1 | 1 | 2005-10-03 | 2005-10-03 |
| GR | 1 | 2012-07-26 | 2012-07-26 |
| HLT1 | 1 | 2007-10-24 | 2007-10-24 |
| KMG1 | 1 | 2006-08-10 | 2006-08-10 |
| LSI1 | 1 | 2014-05-07 | 2014-05-07 |
| MHS | 1 | 2012-04-02 | 2012-04-02 |
| MOLX | 1 | 2013-12-09 | 2013-12-09 |
| MXIM | 1 | 2021-08-27 | 2021-08-27 |
| NLSN | 1 | 2022-10-11 | 2022-10-11 |
| PET1 | 1 | 1998-06-29 | 1998-06-29 |
| PPW | 1 | 1999-11-30 | 1999-11-30 |
| RAI | 1 | 2017-07-25 | 2017-07-25 |
| RAL1 | 1 | 2001-12-13 | 2001-12-13 |
| RNB | 1 | 2000-01-03 | 2000-01-03 |
| RTN | 1 | 2020-04-03 | 2020-04-03 |
| RX | 1 | 2010-02-25 | 2010-02-25 |
| SAF2 | 1 | 2008-09-23 | 2008-09-23 |
| SE1 | 1 | 2017-02-27 | 2017-02-27 |
| SNDK1 | 1 | 2016-05-12 | 2016-05-12 |
| SW | 1 | 2024-07-05 | 2024-07-05 |
| TDC | 1 | 2007-10-01 | 2007-10-01 |
| TEG | 1 | 2015-06-30 | 2015-06-30 |
| USB1 | 1 | 2001-02-26 | 2001-02-26 |
| XLNX | 1 | 2022-02-14 | 2022-02-14 |

## Ticker Identity Diagnostics
Diagnostics only. Historical SP500 tickers are not substituted with related/current tickers.
| ticker | missing_dates | first_missing_date | last_missing_date | sep_metadata_records | metadata_first_price_date | metadata_last_price_date | relatedtickers_examples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CCE1 | 58 | 1998-10-08 | 1998-12-30 | 1 | 1998-12-31 | 2016-05-27 | CCE |
| NBL | 5 | 2020-10-05 | 2020-10-09 | 1 | 1986-01-01 | 2020-10-02 | None |
| AGN1 | 4 | 2015-03-17 | 2015-03-20 | 1 | 1989-06-21 | 2015-03-16 | AGN |
| COL | 4 | 2018-11-27 | 2018-11-30 | 1 | 2001-06-15 | 2018-11-26 | None |
| JNPR | 4 | 2025-07-02 | 2025-07-08 | 1 | 1999-06-25 | 2025-07-01 | None |
| RHT | 4 | 2019-07-09 | 2019-07-12 | 1 | 1999-08-11 | 2019-07-08 | RHAT |
| SUN1 | 4 | 2012-10-04 | 2012-10-09 | 1 | 1986-01-01 | 2012-10-03 | SUN |
| ATVI | 3 | 2023-10-13 | 2023-10-17 | 1 | 1993-10-25 | 2023-10-12 | None |
| CTLT | 3 | 2024-12-18 | 2024-12-20 | 1 | 2014-07-31 | 2024-12-17 | None |
| DAY | 3 | 2026-02-04 | 2026-02-06 | 1 | 2018-04-26 | 2026-02-03 | CDAY |
| HAR | 3 | 2017-03-13 | 2017-03-15 | 1 | 1986-11-14 | 2017-03-10 | None |
| POM1 | 3 | 2016-03-24 | 2016-03-29 | 1 | 1987-01-02 | 2016-03-23 | POM |
| PXD | 3 | 2024-05-03 | 2024-05-07 | 1 | 1987-12-22 | 2024-05-02 | PDP |
| SPLS1 | 3 | 2017-09-13 | 2017-09-15 | 1 | 1990-03-26 | 2017-09-12 | SPLS |
| TOS1 | 3 | 2001-09-17 | 2001-09-19 | 1 | 1986-01-01 | 2001-09-10 | TOS |
| TSS | 3 | 2019-09-18 | 2019-09-20 | 1 | 1989-06-30 | 2019-09-17 | None |
| VAR | 3 | 2021-04-15 | 2021-04-19 | 1 | 1988-01-05 | 2021-04-14 | None |
| AET | 2 | 2018-11-29 | 2018-11-30 | 1 | 1986-01-01 | 2018-11-28 | None |
| AFS.A | 2 | 2000-12-01 | 2000-12-04 | 1 | 1996-05-08 | 2000-11-30 | None |
| BCR | 2 | 2017-12-29 | 2018-01-02 | 1 | 1986-01-01 | 2017-12-28 | None |
| BHI | 2 | 2017-07-05 | 2017-07-06 | 1 | 1987-04-07 | 2017-07-03 | None |
| CXO | 2 | 2021-01-19 | 2021-01-20 | 1 | 2007-08-03 | 2021-01-15 | None |
| DTV1 | 2 | 2015-07-27 | 2015-07-28 | 1 | 2003-12-24 | 2015-07-24 | HS DTV |
| ETFC | 2 | 2020-10-05 | 2020-10-06 | 1 | 1996-08-16 | 2020-10-02 | ET |
| FDC1 | 2 | 2007-09-24 | 2007-09-25 | 1 | 1992-04-09 | 2007-09-21 | FDC |
| GMCR | 2 | 2016-03-03 | 2016-03-04 | 1 | 1993-09-27 | 2016-03-02 | None |
| HES | 2 | 2025-07-21 | 2025-07-22 | 1 | 1986-01-01 | 2025-07-18 | HES-PA AHC AMDPP |
| HOLX | 2 | 2026-04-07 | 2026-04-08 | 1 | 1990-03-26 | 2026-04-06 | None |
| INFO1 | 2 | 2022-02-28 | 2022-03-01 | 1 | 2014-06-19 | 2022-02-25 | MRKT INFO |
| JAVA1 | 2 | 2010-01-27 | 2010-01-28 | 1 | 1986-03-04 | 2010-01-26 | JAVA SUNW |
| MRO | 2 | 2024-11-22 | 2024-11-25 | 1 | 1986-01-01 | 2024-11-21 | None |
| NFX1 | 2 | 2019-02-13 | 2019-02-14 | 1 | 1993-11-12 | 2019-02-12 | NFX |
| TWTR | 2 | 2022-10-28 | 2022-10-31 | 1 | 2013-11-07 | 2022-10-27 | None |
| TWX | 2 | 2018-06-18 | 2018-06-19 | 1 | 1992-03-19 | 2018-06-15 | AOL |
| WCG | 2 | 2020-01-24 | 2020-01-27 | 1 | 2004-07-01 | 2020-01-23 | None |
| XL1 | 2 | 2018-09-12 | 2018-09-13 | 1 | 1991-07-19 | 2018-09-11 | XL |
| ADT1 | 1 | 2016-05-02 | 2016-05-02 | 1 | 2012-09-17 | 2016-04-29 | ADT |
| AGC1 | 1 | 2001-08-29 | 2001-08-29 | 1 | 1986-01-01 | 2001-08-28 | AGC |
| AGN | 1 | 2020-05-11 | 2020-05-11 | 1 | 1989-06-22 | 2020-05-08 | AGN-PA ACT WPI |
| ALTR1 | 1 | 2015-12-28 | 2015-12-28 | 1 | 1988-03-31 | 2015-12-24 | ALTR |
| AT1 | 1 | 2007-11-16 | 2007-11-16 | 1 | 1986-01-01 | 2007-11-15 | AT |
| AWE | 1 | 2001-07-06 | 2001-07-06 | 1 | 2001-07-09 | 2004-10-26 | None |
| BLS | 1 | 2007-01-03 | 2007-01-03 | 1 | 1986-01-01 | 2006-12-29 | None |
| BUD1 | 1 | 2008-11-18 | 2008-11-18 | 1 | 1986-01-01 | 2008-11-17 | BUD |
| CB1 | 1 | 2016-01-15 | 2016-01-15 | 1 | 1986-01-01 | 2016-01-14 | CB |
| CCU1 | 1 | 2008-07-30 | 2008-07-30 | 1 | 1986-01-01 | 2008-07-29 | CCU |
| CFL1 | 1 | 1998-04-28 | 1998-04-28 | 1 | 1986-01-01 | 1998-04-27 | CFL |
| CFN | 1 | 2015-03-17 | 2015-03-17 | 1 | 2009-08-21 | 2015-03-16 | None |
| COC | 1 | 2002-09-03 | 2002-09-03 | 1 | 1999-07-13 | 2002-08-30 | COC.B COC.A |
| CPGX | 1 | 2016-07-01 | 2016-07-01 | 1 | 2015-07-02 | 2016-06-30 | None |
| CTXS | 1 | 2022-09-30 | 2022-09-30 | 1 | 1995-12-08 | 2022-09-29 | None |
| CVC | 1 | 2016-06-21 | 2016-06-21 | 1 | 1992-03-17 | 2016-06-20 | RMG RMG2 |
| CVH | 1 | 2013-05-07 | 2013-05-07 | 1 | 1991-04-17 | 2013-05-06 | CVTY |
| DI1 | 1 | 1998-09-30 | 1998-09-30 | 1 | 1986-01-01 | 1998-09-29 | DI |
| EDS | 1 | 2008-08-26 | 2008-08-26 | 1 | 1986-01-01 | 2008-08-25 | None |
| EMC1 | 1 | 2016-09-07 | 2016-09-07 | 1 | 1988-12-16 | 2016-09-06 | EMC |
| ESRX | 1 | 2018-12-21 | 2018-12-21 | 1 | 1992-06-09 | 2018-12-20 | None |
| FDO | 1 | 2015-07-07 | 2015-07-07 | 1 | 1986-01-01 | 2015-07-06 | None |
| FTI | 1 | 2017-01-13 | 2017-01-13 | 1 | 2017-01-17 | 2026-08-13 | None |
| G1 | 1 | 2005-10-03 | 2005-10-03 | 1 | 1986-01-01 | 2005-09-30 | G |
| GR | 1 | 2012-07-26 | 2012-07-26 | 1 | 1986-01-01 | 2012-07-25 | None |
| HLT1 | 1 | 2007-10-24 | 2007-10-24 | 1 | 1986-01-01 | 2007-10-23 | HLT |
| KMG1 | 1 | 2006-08-10 | 2006-08-10 | 1 | 1986-01-01 | 2006-08-09 | KMG |
| LSI1 | 1 | 2014-05-07 | 2014-05-07 | 1 | 1986-01-01 | 2014-05-06 | LSI |
| MHS | 1 | 2012-04-02 | 2012-04-02 | 1 | 2003-08-20 | 2012-03-30 | None |
| MOLX | 1 | 2013-12-09 | 2013-12-09 | 1 | 1986-01-01 | 2013-12-06 | MOLXA |
| MXIM | 1 | 2021-08-27 | 2021-08-27 | 1 | 1990-03-26 | 2021-08-26 | None |
| NLSN | 1 | 2022-10-11 | 2022-10-11 | 1 | 2011-01-27 | 2022-10-10 | None |
| PET1 | 1 | 1998-06-29 | 1998-06-29 | 1 | 1986-01-01 | 1998-06-26 | PET |
| PPW | 1 | 1999-11-30 | 1999-11-30 | 1 | 1986-01-01 | 1999-11-29 | None |
| RAI | 1 | 2017-07-25 | 2017-07-25 | 1 | 1999-06-01 | 2017-07-24 | RJR |
| RAL1 | 1 | 2001-12-13 | 2001-12-13 | 1 | 1986-01-01 | 2001-12-12 | RAL |
| RNB | 1 | 2000-01-03 | 2000-01-03 | 1 | 1986-01-01 | 1999-12-31 | None |
| RTN | 1 | 2020-04-03 | 2020-04-03 | 1 | 1986-01-01 | 2020-04-02 | None |
| RX | 1 | 2010-02-25 | 2010-02-25 | 1 | 1996-10-17 | 2010-02-24 | None |
| SAF2 | 1 | 2008-09-23 | 2008-09-23 | 1 | 1986-01-01 | 2008-09-22 | SAFC SAF |
| SE1 | 1 | 2017-02-27 | 2017-02-27 | 1 | 2006-12-14 | 2017-02-24 | SE |
| SNDK1 | 1 | 2016-05-12 | 2016-05-12 | 1 | 1995-11-08 | 2016-05-11 | SNDK |
| SW | 1 | 2024-07-05 | 2024-07-05 | 1 | 2024-07-08 | 2026-08-13 | None |
| TDC | 1 | 2007-10-01 | 2007-10-01 | 1 | 2007-10-02 | 2026-08-13 | None |
| TEG | 1 | 2015-06-30 | 2015-06-30 | 1 | 1988-01-05 | 2015-06-29 | WPS |
| USB1 | 1 | 2001-02-26 | 2001-02-26 | 1 | 1986-01-01 | 2001-02-23 | FBS USB |
| XLNX | 1 | 2022-02-14 | 2022-02-14 | 1 | 1990-06-18 | 2022-02-11 | None |

## Benchmark Coverage
| ticker | first_price_date | last_price_date | row_count |
| --- | --- | --- | --- |
| IWM | 2000-05-26 | 2026-08-13 | 6592 |
| QQQ | 1999-03-10 | 2026-08-13 | 6900 |
| RSP | 2003-05-01 | 2026-08-13 | 5859 |
| SPY | 1997-12-31 | 2026-08-13 | 7198 |
| XLB | 1998-12-22 | 2026-08-13 | 6952 |
| XLC | 2018-06-19 | 2026-08-13 | 2049 |
| XLE | 1998-12-22 | 2026-08-13 | 6952 |
| XLF | 1998-12-22 | 2026-08-13 | 6952 |
| XLI | 1998-12-22 | 2026-08-13 | 6952 |
| XLK | 1998-12-22 | 2026-08-13 | 6952 |
| XLP | 1998-12-22 | 2026-08-13 | 6952 |
| XLRE | 2015-10-08 | 2026-08-13 | 2727 |
| XLU | 1998-12-22 | 2026-08-13 | 6952 |
| XLV | 1998-12-22 | 2026-08-13 | 6952 |
| XLY | 1998-12-22 | 2026-08-13 | 6952 |

## Validation Checks
- `historical snapshot dates exist`: pass
- `daily membership has no duplicate (date, ticker) rows`: pass
- `member counts are generally near 500`: pass
- `current reconstructed membership approximately matches action='current'`: pass
- `price coverage is calculated`: pass
- `historical tickers are not silently rewritten`: pass
- `duplicate event-date/ticker cases checked`: pass
- `membership parquet can be queried by DuckDB`: pass
- `current reconciliation has finite diff counts`: pass
