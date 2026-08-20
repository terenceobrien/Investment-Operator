# Sharadar Raw CSV Profile

Generated: `2026-08-14T17:38:13`
Raw directory: `/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/raw`
Total raw CSV size: `12.60 GB`

## Summary

| Table | Size | Rows | Columns | Unique tickers | Date min | Date max | Issues |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ACTIONS | 44.54 MB | 673,126 | 7 | 32,009 | 1997-12-31 | 2026-08-17 |  |
| DAILY | 2.32 GB | ~39,503,737 | 10 | ~6,386 | 1998-12-01 | 2026-08-12 | Row count is estimated in default mode; run with --full-profile for exact Duc... |
| EVENTS | 50.44 MB | 2,541,804 | 3 | 17,807 | 1993-11-08 | 2026-08-13 |  |
| INDICATORS | 85.00 KB | 373 | 7 |  |  |  |  |
| METRICS | 3.73 MB | 31,755 | 22 | 31,755 | 1997-12-31 | 2026-08-13 |  |
| SEP | 3.00 GB | ~46,461,239 | 10 | ~8,152 | 1997-12-31 | 2026-07-17 | Row count is estimated in default mode; run with --full-profile for exact Duc... |
| SF1 | 2.25 GB | ~3,196,475 | 112 | ~1,669 | 1991-06-30 | 2026-12-31 | Row count is estimated in default mode; run with --full-profile for exact Duc... |
| SF2 | 1.10 GB | ~11,505,520 | 24 | ~4,124 | 2025-08-01 | 2026-08-13 | Row count is estimated in default mode; run with --full-profile for exact Duc... |
| SF3A | 86.05 MB | 667,772 | 29 | 30,971 | 2013-06-30 | 2026-06-30 |  |
| SF3B | 42.90 MB | 303,139 | 29 |  | 2013-06-30 | 2026-06-30 |  |
| SF3 | 2.65 GB | ~79,809,754 | 6 | ~6,798 | 2023-06-30 | 2025-06-30 | Row count is estimated in default mode; run with --full-profile for exact Duc... |
| SFP | 1.03 GB | ~15,551,586 | 10 | ~5,109 | 1997-12-31 | 2026-08-03 | Row count is estimated in default mode; run with --full-profile for exact Duc... |
| SP500 | 3.14 MB | 59,672 | 7 | 1,203 | 1957-03-04 | 2026-08-13 |  |
| TICKERS | 19.51 MB | 62,779 | 28 | 31,776 | 2018-06-13 | 2026-08-13 |  |

## ACTIONS

File: `SHARADAR_ACTIONS_2_29fe246cadf640e7e1609af39f779093.csv`
Size: `46705987` bytes (`44.54 MB`)
Rows: `673,126`
Columns: `7`
Elapsed: `1.24s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| date | DATE | 0 | 0.0 | exact_full_table |
| action | VARCHAR | 0 | 0.0 | exact_full_table |
| ticker | VARCHAR | 0 | 0.0 | exact_full_table |
| name | VARCHAR | 0 | 0.0 | exact_full_table |
| value | DOUBLE | 74299 | 11.0379 | exact_full_table |
| contraticker | VARCHAR | 0 | 0.0 | exact_full_table |
| contraname | VARCHAR | 0 | 0.0 | exact_full_table |

### First 5 Rows

| date | action | ticker | name | value | contraticker | contraname |
| --- | --- | --- | --- | --- | --- | --- |
| 2023-12-27 | dividend | CLOI | VANECK CLO ETF | 0.265 | N/A | N/A |
| 2023-12-27 | dividend | CIB | GRUPO CIBEST SA | 0.88353 | N/A | N/A |
| 2023-12-27 | dividend | CHN | CHINA FUND INC | 0.0185 | N/A | N/A |
| 2023-12-27 | dividend | CGXU | CAPITAL GROUP INTERNATIONAL FOCUS EQUITY ETF | 0.096 | N/A | N/A |
| 2023-12-27 | dividend | CGUS | CAPITAL GROUP CORE EQUITY ETF | 0.102 | N/A | N/A |

### Last 5 Rows

| date | action | ticker | name | value | contraticker | contraname |
| --- | --- | --- | --- | --- | --- | --- |
| 2004-12-29 | dividend | KPA | INNKEEPERS USA TRUST | 0.06 | N/A | N/A |
| 2004-12-29 | dividend | KOSS | KOSS CORP | 0.065 | N/A | N/A |
| 2004-12-29 | dividend | KNAP | KNAPE & VOGT MANUFACTURING CO | 0.165 | N/A | N/A |
| 2004-12-29 | dividend | KHI | DEUTSCHE HIGH INCOME TRUST | 0.106 | N/A | N/A |
| 2004-12-29 | dividend | KF | KOREA FUND INC | 6.5 | N/A | N/A |

### Date Coverage

**date**
- `min_date`: 1997-12-31
- `max_date`: 2026-08-17
- `parsed_rows`: 673126
- `profiled_rows`: 673126
- `scope`: exact_full_table

### Identifier Distinct Counts

**date**
- `column`: date
- `distinct_count`: 7348
- `scope`: exact_full_table
**ticker**
- `column`: ticker
- `distinct_count`: 32009
- `scope`: exact_full_table

### Categorical Values

**action**
| value | row_count |
| --- | --- |
| dividend | 550231 |
| listed | 23368 |
| delisted | 19231 |
| tickerchangefrom | 13455 |
| tickerchangeto | 13455 |
| split | 12926 |
| relation | 8618 |
| initiated | 8407 |
| acquisitionby | 8257 |
| acquisitionof | 8257 |

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 2634 | 1601 | ['ticker', 'date', 'action'] | exact_full_table |
| 2634 | 1601 | ['ticker', 'action', 'date'] | exact_full_table |

### Table-Specific Checks

**action_type_fields**
- `action`
**ticker_identifier_fields**
- `ticker`
**effective_date_fields**
- `date`
**date_fields**
**date**
- `min_date`: 1997-12-31
- `max_date`: 2026-08-17
- `parsed_rows`: 673126
- `profiled_rows`: 673126
- `scope`: exact_full_table
**action_values**
| value | row_count |
| --- | --- |
| dividend | 550231 |
| listed | 23368 |
| delisted | 19231 |
| tickerchangefrom | 13455 |
| tickerchangeto | 13455 |
| split | 12926 |
| relation | 8618 |
| initiated | 8407 |
| acquisitionby | 8257 |
| acquisitionof | 8257 |
| bankruptcyliquidation | 3348 |
| regulatorydelisting | 887 |
| spinoff | 566 |
| spunofffrom | 566 |
| spinoffdividend | 522 |
| adrratiosplit | 386 |
| voluntarydelisting | 378 |
| mergerfrom | 134 |
| mergerto | 134 |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/ACTIONS_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.006 |
| duckdb_view_and_schema | 0.106 |
| example_rows | 0.212 |
| row_count | 0.072 |
| null_profile | 0.158 |
| date_ranges | 0.076 |
| distincts_and_categories | 0.222 |
| duplicate_key_checks | 0.182 |
| table_specific_checks | 0.151 |
| sample_csv | 0.055 |

## DAILY

File: `SHARADAR_DAILY_3_1eb3b706c850f0fffb2209ff783014bf.csv`
Size: `2492968683` bytes (`2.32 GB`)
Rows: `~39,503,737`
Columns: `10`
Elapsed: `0.94s`

### Issues And Warnings

- Warning: Row count is estimated in default mode; run with --full-profile for exact DuckDB count.
- Warning: Null counts and percentages are sample-based in default mode for large tables.
- Warning: Duplicate key checks are sample-based in default mode for this table.

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| date | DATE | 0 | 0.0 | sample_first_100000_rows |
| lastupdated | DATE | 0 | 0.0 | sample_first_100000_rows |
| ev | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| evebit | DOUBLE | 3270 | 3.27 | sample_first_100000_rows |
| evebitda | DOUBLE | 3960 | 3.96 | sample_first_100000_rows |
| marketcap | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| pb | DOUBLE | 32 | 0.032 | sample_first_100000_rows |
| pe | DOUBLE | 3317 | 3.317 | sample_first_100000_rows |
| ps | DOUBLE | 11680 | 11.68 | sample_first_100000_rows |

### First 5 Rows

| ticker | date | lastupdated | ev | evebit | evebitda | marketcap | pb | pe | ps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 2021-09-01 | 2021-09-01 | 54542.7 | 42.8 | 34.4 | 53112.7 | 10.7 | 53.6 | 8.6 |
| AA | 2021-09-01 | 2021-09-01 | 9086.1 | 10.2 | 5.8 | 8521.1 | 2.3 | 19.8 | 0.8 |
| AEM | 2022-10-26 | 2022-10-26 | 21040.9 | 18.9 | 9.9 | 20392.1 | 1.3 | 35.9 | 3.8 |
| AGR | 2022-10-26 | 2022-10-26 | 24151.1 | 19.5 | 10.5 | 15461.1 | 0.8 | 17.2 | 2.0 |
| AIAI | 2026-05-15 | 2026-05-17 | 1038.5 | 127.1 |  | 1039.5 | 155.8 | 153.4 | 4.1 |

### Last 5 Rows

_Skipped in fast mode or not inexpensive for this table._

### Date Coverage

**date**
- `min_date`: 1998-12-01
- `max_date`: 2026-08-12
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**lastupdated**
- `min_date`: 2021-01-22
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 6386
- `scope`: sample_first_100000_rows
**date**
- `column`: date
- `distinct_count`: 4699
- `scope`: sample_first_100000_rows

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | sample_first_100000_rows |

### Table-Specific Checks

**ticker_identifier_fields**
- `ticker`
**daily_metric_columns**
- `ev`
- `evebit`
- `evebitda`
- `marketcap`
- `pb`
- `pe`
- `ps`
**date_range**
- `min_date`: 1998-12-01
- `max_date`: 2026-08-12
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**unique_ticker_count**
- `column`: ticker
- `distinct_count`: 6329
- `scope`: sample_first_100000_rows
**duplicate_key_behavior**
| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | sample_first_100000_rows |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/DAILY_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.007 |
| duckdb_view_and_schema | 0.12 |
| example_rows | 0.068 |
| row_count | 0.003 |
| null_profile | 0.138 |
| date_ranges | 0.135 |
| distincts_and_categories | 0.131 |
| duplicate_key_checks | 0.068 |
| table_specific_checks | 0.203 |
| sample_csv | 0.066 |

## EVENTS

File: `SHARADAR_EVENTS_2_f7652fc210db5975999b569d7b899841.csv`
Size: `52888671` bytes (`50.44 MB`)
Rows: `2,541,804`
Columns: `3`
Elapsed: `1.11s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | exact_full_table |
| date | DATE | 0 | 0.0 | exact_full_table |
| eventcodes | VARCHAR | 0 | 0.0 | exact_full_table |

### First 5 Rows

| ticker | date | eventcodes |
| --- | --- | --- |
| AACB | 2026-08-13 | 81 |
| AAON | 2026-08-13 | 81\|91 |
| AAPG | 2026-08-13 | 81 |
| ABCL | 2026-08-13 | 11\|81\|91 |
| ABEO | 2026-08-13 | 22\|91 |

### Last 5 Rows

| ticker | date | eventcodes |
| --- | --- | --- |
| IFIN1 | 2006-08-16 | 52 |
| IFS3 | 2006-08-16 | 35 |
| IHR | 2006-08-16 | 35 |
| IKAN | 2006-08-16 | 22\|91 |
| INCLF | 2006-08-16 | 37 |

### Date Coverage

**date**
- `min_date`: 1993-11-08
- `max_date`: 2026-08-13
- `parsed_rows`: 2541804
- `profiled_rows`: 2541804
- `scope`: exact_full_table

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 17807
- `scope`: exact_full_table
**date**
- `column`: date
- `distinct_count`: 8178
- `scope`: exact_full_table

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | exact_full_table |

### Table-Specific Checks

**event_date_fields**
- `date`
**event_type_category_fields**
- `eventcodes`
**ticker_identifier_fields**
- `ticker`
**date_fields**
**date**
- `min_date`: 1993-11-08
- `max_date`: 2026-08-13
- `parsed_rows`: 2541804
- `profiled_rows`: 2541804
- `scope`: exact_full_table
**eventcodes_values**
| value | row_count |
| --- | --- |
| 81 | 490352 |
| 34 | 467494 |
| 22\|91 | 259466 |
| 81\|91 | 203351 |
| 35 | 127722 |
| 71\|91 | 122288 |
| 52 | 77478 |
| 52\|91 | 66335 |
| 22\|71\|91 | 50602 |
| 11\|91 | 49751 |
| 57 | 42650 |
| 71 | 32974 |
| 21\|91 | 30816 |
| 37 | 25262 |
| 11\|23\|91 | 22513 |
| 91 | 21840 |
| 11 | 19154 |
| 22\|81\|91 | 18891 |
| 11\|81\|91 | 14943 |
| 71\|81\|91 | 14467 |
| 52\|71\|91 | 14315 |
| 22 | 11586 |
| 53\|91 | 11261 |
| 21 | 10081 |
| 11\|71\|91 | 9833 |
| 52\|81\|91 | 9609 |
| 31 | 8151 |
| 41\|91 | 7253 |
| 22\|52\|91 | 6863 |
| 52\|57\|91 | 6805 |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/EVENTS_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.003 |
| duckdb_view_and_schema | 0.067 |
| example_rows | 0.201 |
| row_count | 0.076 |
| null_profile | 0.164 |
| date_ranges | 0.089 |
| distincts_and_categories | 0.168 |
| duplicate_key_checks | 0.128 |
| table_specific_checks | 0.172 |
| sample_csv | 0.038 |

## INDICATORS

File: `SHARADAR_INDICATORS_2_bc740820ddbdc608c936845d8d949622.csv`
Size: `87043` bytes (`85.00 KB`)
Rows: `373`
Columns: `7`
Elapsed: `0.12s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| table | VARCHAR | 0 | 0.0 | exact_full_table |
| indicator | VARCHAR | 0 | 0.0 | exact_full_table |
| isfilter | VARCHAR | 0 | 0.0 | exact_full_table |
| isprimarykey | VARCHAR | 0 | 0.0 | exact_full_table |
| title | VARCHAR | 0 | 0.0 | exact_full_table |
| description | VARCHAR | 6 | 1.6086 | exact_full_table |
| unittype | VARCHAR | 0 | 0.0 | exact_full_table |

### First 5 Rows

| table | indicator | isfilter | isprimarykey | title | description | unittype |
| --- | --- | --- | --- | --- | --- | --- |
| SF1 | revenue | N | N | Revenues | [Income Statement] The amount of Revenue recognised from goods sold; services... | currency |
| SF1 | cor | N | N | Cost of Revenue | [Income Statement] The aggregate cost of goods produced and sold and services... | currency |
| SF1 | sgna | N | N | Selling General and Administrative Expense | [Income Statement] A component of [OpEx] representing the aggregate total cos... | currency |
| SF1 | rnd | N | N | Research and Development Expense | [Income Statement] A component of [OpEx] representing the aggregate costs inc... | currency |
| SF1 | opex | N | N | Operating Expenses | [Income Statement] Operating expenses represent the total expenditure on [SGn... | currency |

### Last 5 Rows

| table | indicator | isfilter | isprimarykey | title | description | unittype |
| --- | --- | --- | --- | --- | --- | --- |
| TICKERS | lastpricedate | N | N | Last Price Date | The most recent price observation available. | date (YYYY-MM-DD) |
| TICKERS | firstquarter | N | N | First Quarter | The first financial quarter available in the dataset. | date (YYYY-MM-DD) |
| TICKERS | lastquarter | N | N | Last Quarter | The last financial quarter available in the dataset. | date (YYYY-MM-DD) |
| TICKERS | secfilings | N | N | SEC Filings URL | The URL pointing to the SEC filings which also contains the Central Index Key... | text |
| TICKERS | companysite | N | N | Company Website URL | The URL pointing to the company website. | text |

### Date Coverage

_None._

### Identifier Distinct Counts

_None._

### Categorical Values

**table**
| value | row_count |
| --- | --- |
| SF1 | 112 |
| EVENTCODES | 37 |
| SF3A | 29 |
| SF3B | 28 |
| TICKERS | 28 |
| SF2 | 24 |
| METRICS | 22 |
| ACTIONTYPES | 19 |
| TABLE-DESCRIPTIONS | 14 |
| DAILY | 10 |

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['table', 'indicator'] | exact_full_table |

### Table-Specific Checks

**metadata_fields**
- `table`
- `isfilter`
- `isprimarykey`
- `description`
- `unittype`
**representative_rows**
| table | indicator | isfilter | isprimarykey | title | description | unittype |
| --- | --- | --- | --- | --- | --- | --- |
| SF1 | revenue | N | N | Revenues | [Income Statement] The amount of Revenue recognised from goods sold; services... | currency |
| SF1 | cor | N | N | Cost of Revenue | [Income Statement] The aggregate cost of goods produced and sold and services... | currency |
| SF1 | sgna | N | N | Selling General and Administrative Expense | [Income Statement] A component of [OpEx] representing the aggregate total cos... | currency |
| SF1 | rnd | N | N | Research and Development Expense | [Income Statement] A component of [OpEx] representing the aggregate costs inc... | currency |
| SF1 | opex | N | N | Operating Expenses | [Income Statement] Operating expenses represent the total expenditure on [SGn... | currency |
| SF1 | intexp | N | N | Interest Expense | [Income Statement] Amount of the cost of borrowed funds accounted for as inte... | currency |
| SF1 | taxexp | N | N | Income Tax Expense | [Income Statement] Amount of current income tax expense (benefit) and deferre... | currency |
| SF1 | netincdis | N | N | Net Loss Income from Discontinued Operations | [Income Statement] Amount of loss (income) from a disposal group; net of inco... | currency |
| SF1 | consolinc | N | N | Consolidated Income | [Income Statement] The portion of profit or loss for the period; net of incom... | currency |
| SF1 | netincnci | N | N | Net Income to Non-Controlling Interests | [Income Statement] The portion of income which is attributable to non-control... | currency |
| SF1 | netinc | N | N | Net Income | [Income Statement] The portion of profit or loss for the period; net of incom... | currency |
| SF1 | prefdivis | N | N | Preferred Dividends Income Statement Impact | [Income Statement] Income statement item reflecting dividend payments to pref... | currency |
| SF1 | netinccmn | N | N | Net Income Common Stock | [Income Statement] The amount of net income (loss) for the period due to comm... | currency |
| SF1 | eps | N | N | Earnings per Basic Share | [Income Statement] Earnings per share as calculated and reported by the compa... | currency/share |
| SF1 | epsdil | N | N | Earnings per Diluted Share | [Income Statement] Earnings per diluted share as calculated and reported by t... | currency/share |
| SF1 | shareswa | N | N | Weighted Average Shares | [Income Statement] The weighted average number of shares or units issued and ... | units |
| SF1 | shareswadil | N | N | Weighted Average Shares Diluted | [Income Statement] The weighted average number of shares or units issued and ... | units |
| SF1 | capex | N | N | Capital Expenditure | [Cash Flow Statement] A component of [NCFI] representing the net cash inflow ... | currency |
| SF1 | ncfbus | N | N | Net Cash Flow - Business Acquisitions and Disposals | [Cash Flow Statement] A component of [NCFI] representing the net cash inflow ... | currency |
| SF1 | ncfinv | N | N | Net Cash Flow - Investment Acquisitions and Disposals | [Cash Flow Statement] A component of [NCFI] representing the net cash inflow ... | currency |
**table_values**
| value | row_count |
| --- | --- |
| SF1 | 112 |
| EVENTCODES | 37 |
| SF3A | 29 |
| SF3B | 28 |
| TICKERS | 28 |
| SF2 | 24 |
| METRICS | 22 |
| ACTIONTYPES | 19 |
| TABLE-DESCRIPTIONS | 14 |
| DAILY | 10 |
| SEP | 10 |
| SFP | 10 |
| ACTIONS | 7 |
| INDICATORS | 7 |
| SP500 | 7 |
| SF3 | 6 |
| EVENTS | 3 |
**indicator_values**
| value | row_count |
| --- | --- |
| ticker | 12 |
| date | 7 |
| lastupdated | 6 |
| calendardate | 4 |
| name | 4 |
| volume | 3 |
| action | 2 |
| cllunits | 2 |
| cllvalue | 2 |
| close | 2 |
| closeadj | 2 |
| closeunadj | 2 |
| contraname | 2 |
| contraticker | 2 |
| dbtunits | 2 |
| dbtvalue | 2 |
| ev | 2 |
| evebit | 2 |
| evebitda | 2 |
| fndunits | 2 |
| fndvalue | 2 |
| high | 2 |
| investorname | 2 |
| low | 2 |
| marketcap | 2 |
| open | 2 |
| pb | 2 |
| pe | 2 |
| percentoftotal | 2 |
| prfunits | 2 |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/INDICATORS_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.001 |
| duckdb_view_and_schema | 0.017 |
| example_rows | 0.024 |
| row_count | 0.008 |
| null_profile | 0.016 |
| date_ranges | 0.0 |
| distincts_and_categories | 0.01 |
| duplicate_key_checks | 0.009 |
| table_specific_checks | 0.026 |
| sample_csv | 0.008 |

## METRICS

File: `SHARADAR_METRICS_d6a4abf74034e524af8f2de5581a10eb.csv`
Size: `3909070` bytes (`3.73 MB`)
Rows: `31,755`
Columns: `22`
Elapsed: `2.32s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | exact_full_table |
| date | DATE | 0 | 0.0 | exact_full_table |
| lastupdated | DATE | 0 | 0.0 | exact_full_table |
| beta1y | DOUBLE | 125 | 0.3936 | exact_full_table |
| beta5y | DOUBLE | 715 | 2.2516 | exact_full_table |
| dividendyieldforward | DOUBLE | 1213 | 3.8199 | exact_full_table |
| dividendyieldtrailing | DOUBLE | 558 | 1.7572 | exact_full_table |
| high52w | DOUBLE | 0 | 0.0 | exact_full_table |
| high5y | DOUBLE | 0 | 0.0 | exact_full_table |
| low52w | DOUBLE | 0 | 0.0 | exact_full_table |
| low5y | DOUBLE | 0 | 0.0 | exact_full_table |
| ma200d | DOUBLE | 2293 | 7.2209 | exact_full_table |
| ma200w | DOUBLE | 23373 | 73.6042 | exact_full_table |
| ma50d | DOUBLE | 574 | 1.8076 | exact_full_table |
| ma50w | DOUBLE | 18369 | 57.846 | exact_full_table |
| price | DOUBLE | 0 | 0.0 | exact_full_table |
| return1y | DOUBLE | 3006 | 9.4662 | exact_full_table |
| return5y | DOUBLE | 14312 | 45.0701 | exact_full_table |
| returnytd | DOUBLE | 0 | 0.0 | exact_full_table |
| volume | BIGINT | 0 | 0.0 | exact_full_table |
| volumeavg1m | BIGINT | 0 | 0.0 | exact_full_table |
| volumeavg3m | BIGINT | 0 | 0.0 | exact_full_table |

### First 5 Rows

| ticker | date | lastupdated | beta1y | beta5y | dividendyieldforward | dividendyieldtrailing | high52w | high5y | low52w | low5y | ma200d | ma200w | ma50d | ma50w | price | return1y | return5y | returnytd | volume | volumeavg1m | volumeavg3m |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KTII | 2010-04-01 | 2026-08-13 | 0.99 | 1.64 | 0.0 | 0.0 | 150.01 | 170.0 | 57.86 | 27.12 | 109.75 |  | 149.42 |  | 150.01 | 138.95 | 392.81 | 463.95 | 72500 | 27228 | 34404 |
| AIR | 2026-08-13 | 2026-08-13 | 1.73 | 1.06 | 0.0 | 0.0 | 153.86 | 153.86 | 71.67 | 30.9 | 109.93 | 72.1 | 134.98 | 104.97 | 143.39 | 83.81 | 321.74 | 73.2 | 328453 | 424229 | 431774 |
| TNZ | 1998-02-02 | 2026-08-13 | 0.1 | 0.29 | 0.0 | 0.97 | 30.88 | 30.88 | 15.0 | 10.12 | 24.06 |  | 28.42 |  | 29.0 | 85.19 | 79.93 | 54.22 | 76500 | 16890 | 6796 |
| ABT | 2026-08-13 | 2026-08-13 | 0.04 | 0.55 | 2.26 | 2.23 | 137.49 | 142.6 | 81.97 | 81.97 | 107.44 | 112.31 | 97.14 | 111.56 | 111.27 | -13.11 | 0.36 | -9.55 | 4231822 | 9922746 | 11834467 |
| SERV1 | 2011-08-29 | 2026-08-13 | 0.12 | 0.21 | 0.0 | 1.14 | 3.6 | 7.24 | 2.02 | 1.07 | 2.72 |  | 3.33 |  | 3.51 | 70.04 | 3.09 | 1.84 | 52500 | 6623 | 12750 |

### Last 5 Rows

| ticker | date | lastupdated | beta1y | beta5y | dividendyieldforward | dividendyieldtrailing | high52w | high5y | low52w | low5y | ma200d | ma200w | ma50d | ma50w | price | return1y | return5y | returnytd | volume | volumeavg1m | volumeavg3m |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SITX | 2026-08-13 | 2026-08-13 |  |  | 0.0 | 0.0 | 26.74 | 26.74 | 23.38 | 23.38 |  |  |  |  | 24.8 |  |  | 6.09 | 5818 | 5817 | 5817 |
| UMCU | 2026-08-13 | 2026-08-13 |  |  | 0.0 | 0.0 | 27.04 | 27.04 | 25.36 | 25.36 |  |  |  |  | 26.59 |  |  | 4.84 | 708 | 660 | 660 |
| STLL | 2026-08-13 | 2026-08-13 |  |  | 0.0 | 0.0 | 16.88 | 16.88 | 15.21 | 15.21 |  |  |  |  | 16.37 |  |  | 7.22 | 14037 | 10077 | 10077 |
| LITG | 2026-08-13 | 2026-08-13 |  |  | 0.0 | 0.0 | 20.53 | 20.53 | 14.69 | 14.69 |  |  |  |  | 17.31 |  |  | 12.84 | 5742 | 7728 | 7728 |
| MXLL | 2026-08-13 | 2026-08-13 |  |  | 0.0 | 0.0 | 19.45 | 19.45 | 15.29 | 15.29 |  |  |  |  | 18.37 |  |  | 20.15 | 13433 | 8746 | 8746 |

### Date Coverage

**date**
- `min_date`: 1997-12-31
- `max_date`: 2026-08-13
- `parsed_rows`: 31755
- `profiled_rows`: 31755
- `scope`: exact_full_table
**lastupdated**
- `min_date`: 2026-08-13
- `max_date`: 2026-08-13
- `parsed_rows`: 31755
- `profiled_rows`: 31755
- `scope`: exact_full_table

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 31755
- `scope`: exact_full_table
**date**
- `column`: date
- `distinct_count`: 5996
- `scope`: exact_full_table

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker'] | exact_full_table |
| 0 | 0 | ['ticker', 'date'] | exact_full_table |

### Table-Specific Checks

**date_fields**
**date**
- `min_date`: 1997-12-31
- `max_date`: 2026-08-13
- `parsed_rows`: 31755
- `profiled_rows`: 31755
- `scope`: exact_full_table
**lastupdated**
- `min_date`: 2026-08-13
- `max_date`: 2026-08-13
- `parsed_rows`: 31755
- `profiled_rows`: 31755
- `scope`: exact_full_table
**unique_tickers**
- `column`: ticker
- `distinct_count`: 31755
- `scope`: exact_full_table
**distinct_date_counts**
**date**
- `column`: date
- `distinct_count`: 5996
- `scope`: exact_full_table
**lastupdated**
- `column`: lastupdated
- `distinct_count`: 1
- `scope`: exact_full_table
- `current_vs_historical_evidence`: Multiple distinct date values detected; this may contain historical observations.

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/METRICS_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.013 |
| duckdb_view_and_schema | 0.208 |
| example_rows | 0.345 |
| row_count | 0.115 |
| null_profile | 0.243 |
| date_ranges | 0.236 |
| distincts_and_categories | 0.234 |
| duplicate_key_checks | 0.235 |
| table_specific_checks | 0.586 |
| sample_csv | 0.104 |

## SEP

File: `SHARADAR_SEP_2_da2386a176421f8ccbec6fabe5d11c0e.csv`
Size: `3225064238` bytes (`3.00 GB`)
Rows: `~46,461,239`
Columns: `10`
Elapsed: `10.75s`

### Issues And Warnings

- Warning: Row count is estimated in default mode; run with --full-profile for exact DuckDB count.
- Warning: Null counts and percentages are sample-based in default mode for large tables.
- Warning: Duplicate key checks are sample-based in default mode for this table.

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| date | DATE | 0 | 0.0 | sample_first_100000_rows |
| open | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| high | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| low | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| close | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| volume | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| closeadj | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| closeunadj | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| lastupdated | DATE | 0 | 0.0 | sample_first_100000_rows |

### First 5 Rows

| ticker | date | open | high | low | close | volume | closeadj | closeunadj | lastupdated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ABILF | 2021-11-09 | 0.3 | 0.33 | 0.3 | 0.33 | 7500.0 | 0.33 | 0.33 | 2021-11-09 |
| ABILF | 2021-11-08 | 0.35 | 0.35 | 0.35 | 0.35 | 0.0 | 0.35 | 0.35 | 2021-11-09 |
| AAC.U | 2026-07-17 | 10.09 | 10.09 | 10.09 | 10.09 | 100.0 | 10.09 | 10.09 | 2026-07-17 |
| AACI | 2026-07-16 | 9.97 | 9.97 | 9.97 | 9.97 | 0.0 | 9.97 | 9.97 | 2026-07-17 |
| AAC.WS | 2021-09-24 | 0.92 | 0.92 | 0.87 | 0.89 | 38784.0 | 0.89 | 0.89 | 2021-09-24 |

### Last 5 Rows

_Skipped in fast mode or not inexpensive for this table._

### Date Coverage

**date**
- `min_date`: 1997-12-31
- `max_date`: 2026-07-17
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**lastupdated**
- `min_date`: 2021-04-23
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 8152
- `scope`: sample_first_100000_rows
**date**
- `column`: date
- `distinct_count`: 7061
- `scope`: sample_first_100000_rows

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | sample_first_100000_rows |

### Table-Specific Checks

**inspected_fields**
- `ticker`
- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `closeunadj`
- `closeadj`
- `lastupdated`
**price_columns_available**
- `open`
- `high`
- `low`
- `close`
- `volume`
- `closeadj`
- `closeunadj`
- `lastupdated`
**unique_tickers**
- `column`: ticker
- `distinct_count`: 8057
- `scope`: sample_first_100000_rows
**date_range**
- `min_date`: 1997-12-31
- `max_date`: 2026-07-17
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**duplicate_ticker_date**
- `duplicate_rows`: 0
- `duplicate_keys`: 0
**key**
- `ticker`
- `date`
- `scope`: sample_first_100000_rows
**sort_order_sample**
- `sampled_rows`: 5000
- `ticker_date_sorted`: False
- `date_ticker_sorted`: False
**first_last_date_by_sample_ticker**
| ticker | first_date | last_date | rows |
| --- | --- | --- | --- |
| ACIC | 2007-11-07 | 2026-08-13 | 4720 |
| ADNH | 2018-11-16 | 2025-11-03 | 1749 |
| CA1 | 1997-12-31 | 2018-11-05 | 5247 |
| HBIO | 2001-03-19 | 2026-08-13 | 6389 |
| PTEIQ | 2005-01-26 | 2023-06-15 | 4629 |
- `delisted_presence_inferable_from_sep`: False

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SEP_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.007 |
| duckdb_view_and_schema | 0.133 |
| example_rows | 0.082 |
| row_count | 0.003 |
| null_profile | 0.152 |
| date_ranges | 0.138 |
| distincts_and_categories | 0.137 |
| duplicate_key_checks | 0.071 |
| table_specific_checks | 9.961 |
| sample_csv | 0.069 |

## SF1

File: `SHARADAR_SF1_3_a158fbb8637a13efbab2ba75fc06dc74.csv`
Size: `2413164672` bytes (`2.25 GB`)
Rows: `~3,196,475`
Columns: `112`
Elapsed: `15.21s`

### Issues And Warnings

- Warning: Row count is estimated in default mode; run with --full-profile for exact DuckDB count.
- Warning: Null counts and percentages are sample-based in default mode for large tables.
- Warning: Duplicate key checks are sample-based in default mode for this table.

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| dimension | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| calendardate | DATE | 0 | 0.0 | sample_first_100000_rows |
| datekey | DATE | 0 | 0.0 | sample_first_100000_rows |
| reportperiod | DATE | 0 | 0.0 | sample_first_100000_rows |
| fiscalperiod | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| lastupdated | DATE | 0 | 0.0 | sample_first_100000_rows |
| accoci | BIGINT | 3240 | 3.24 | sample_first_100000_rows |
| assets | BIGINT | 3270 | 3.27 | sample_first_100000_rows |
| assetsavg | BIGINT | 50749 | 50.749 | sample_first_100000_rows |
| assetsc | BIGINT | 17670 | 17.67 | sample_first_100000_rows |
| assetsnc | BIGINT | 17701 | 17.701 | sample_first_100000_rows |
| assetturnover | DOUBLE | 51309 | 51.309 | sample_first_100000_rows |
| bvps | DOUBLE | 4007 | 4.007 | sample_first_100000_rows |
| capex | BIGINT | 7468 | 7.468 | sample_first_100000_rows |
| cashneq | BIGINT | 3235 | 3.235 | sample_first_100000_rows |
| cashnequsd | BIGINT | 3235 | 3.235 | sample_first_100000_rows |
| cor | BIGINT | 5031 | 5.031 | sample_first_100000_rows |
| consolinc | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| currentratio | DOUBLE | 17998 | 17.998 | sample_first_100000_rows |
| de | DOUBLE | 3260 | 3.26 | sample_first_100000_rows |
| debt | BIGINT | 3228 | 3.228 | sample_first_100000_rows |
| debtc | BIGINT | 17572 | 17.572 | sample_first_100000_rows |
| debtnc | BIGINT | 17763 | 17.763 | sample_first_100000_rows |
| debtusd | BIGINT | 3228 | 3.228 | sample_first_100000_rows |
| deferredrev | BIGINT | 3240 | 3.24 | sample_first_100000_rows |
| depamor | BIGINT | 8005 | 8.005 | sample_first_100000_rows |
| deposits | BIGINT | 3240 | 3.24 | sample_first_100000_rows |
| divyield | DOUBLE | 5950 | 5.95 | sample_first_100000_rows |
| dps | DOUBLE | 16 | 0.016 | sample_first_100000_rows |
| ebit | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| ebitda | BIGINT | 8201 | 8.201 | sample_first_100000_rows |
| ebitdamargin | DOUBLE | 12485 | 12.485 | sample_first_100000_rows |
| ebitdausd | BIGINT | 8201 | 8.201 | sample_first_100000_rows |
| ebitusd | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| ebt | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| eps | DOUBLE | 6022 | 6.022 | sample_first_100000_rows |
| epsdil | DOUBLE | 9192 | 9.192 | sample_first_100000_rows |
| epsusd | DOUBLE | 6022 | 6.022 | sample_first_100000_rows |
| equity | BIGINT | 3239 | 3.239 | sample_first_100000_rows |
| equityavg | BIGINT | 50732 | 50.732 | sample_first_100000_rows |
| equityusd | BIGINT | 3239 | 3.239 | sample_first_100000_rows |
| ev | BIGINT | 9529 | 9.529 | sample_first_100000_rows |
| evebit | BIGINT | 13035 | 13.035 | sample_first_100000_rows |
| evebitda | DOUBLE | 15598 | 15.598 | sample_first_100000_rows |
| fcf | BIGINT | 7489 | 7.489 | sample_first_100000_rows |
| fcfps | DOUBLE | 8474 | 8.474 | sample_first_100000_rows |
| fxusd | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| gp | BIGINT | 5031 | 5.031 | sample_first_100000_rows |
| grossmargin | DOUBLE | 9457 | 9.457 | sample_first_100000_rows |
| intangibles | BIGINT | 3238 | 3.238 | sample_first_100000_rows |
| intexp | BIGINT | 5039 | 5.039 | sample_first_100000_rows |
| invcap | BIGINT | 3270 | 3.27 | sample_first_100000_rows |
| invcapavg | BIGINT | 50749 | 50.749 | sample_first_100000_rows |
| inventory | BIGINT | 3253 | 3.253 | sample_first_100000_rows |
| investments | BIGINT | 3263 | 3.263 | sample_first_100000_rows |
| investmentsc | BIGINT | 17670 | 17.67 | sample_first_100000_rows |
| investmentsnc | BIGINT | 17670 | 17.67 | sample_first_100000_rows |
| liabilities | BIGINT | 3252 | 3.252 | sample_first_100000_rows |
| liabilitiesc | BIGINT | 17769 | 17.769 | sample_first_100000_rows |
| liabilitiesnc | BIGINT | 17788 | 17.788 | sample_first_100000_rows |
| marketcap | BIGINT | 8718 | 8.718 | sample_first_100000_rows |
| ncf | BIGINT | 7531 | 7.531 | sample_first_100000_rows |
| ncfbus | BIGINT | 10990 | 10.99 | sample_first_100000_rows |
| ncfcommon | BIGINT | 9056 | 9.056 | sample_first_100000_rows |
| ncfdebt | BIGINT | 8483 | 8.483 | sample_first_100000_rows |
| ncfdiv | BIGINT | 11813 | 11.813 | sample_first_100000_rows |
| ncff | BIGINT | 7491 | 7.491 | sample_first_100000_rows |
| ncfi | BIGINT | 7468 | 7.468 | sample_first_100000_rows |
| ncfinv | BIGINT | 10163 | 10.163 | sample_first_100000_rows |
| ncfo | BIGINT | 7486 | 7.486 | sample_first_100000_rows |
| ncfx | BIGINT | 7658 | 7.658 | sample_first_100000_rows |
| netinc | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| netinccmn | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| netinccmnusd | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| netincdis | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| netincnci | BIGINT | 5054 | 5.054 | sample_first_100000_rows |
| netmargin | DOUBLE | 9480 | 9.48 | sample_first_100000_rows |
| opex | BIGINT | 5029 | 5.029 | sample_first_100000_rows |
| opinc | BIGINT | 5031 | 5.031 | sample_first_100000_rows |
| payables | BIGINT | 3199 | 3.199 | sample_first_100000_rows |
| payoutratio | DOUBLE | 7209 | 7.209 | sample_first_100000_rows |
| pb | DOUBLE | 8851 | 8.851 | sample_first_100000_rows |
| pe | DOUBLE | 12141 | 12.141 | sample_first_100000_rows |
| pe1 | DOUBLE | 12007 | 12.007 | sample_first_100000_rows |
| ppnenet | BIGINT | 3208 | 3.208 | sample_first_100000_rows |
| prefdivis | BIGINT | 5017 | 5.017 | sample_first_100000_rows |
| price | DOUBLE | 5803 | 5.803 | sample_first_100000_rows |
| ps | DOUBLE | 15539 | 15.539 | sample_first_100000_rows |
| ps1 | DOUBLE | 14725 | 14.725 | sample_first_100000_rows |
| receivables | BIGINT | 3208 | 3.208 | sample_first_100000_rows |
| retearn | BIGINT | 7056 | 7.056 | sample_first_100000_rows |
| revenue | BIGINT | 4991 | 4.991 | sample_first_100000_rows |
| revenueusd | BIGINT | 4991 | 4.991 | sample_first_100000_rows |
| rnd | BIGINT | 5006 | 5.006 | sample_first_100000_rows |
| roa | DOUBLE | 51298 | 51.298 | sample_first_100000_rows |
| roe | DOUBLE | 51288 | 51.288 | sample_first_100000_rows |
| roic | DOUBLE | 51415 | 51.415 | sample_first_100000_rows |
| ros | DOUBLE | 49919 | 49.919 | sample_first_100000_rows |
| sbcomp | BIGINT | 9151 | 9.151 | sample_first_100000_rows |
| sgna | BIGINT | 4992 | 4.992 | sample_first_100000_rows |
| sharefactor | DOUBLE | 176 | 0.176 | sample_first_100000_rows |
| sharesbas | BIGINT | 4631 | 4.631 | sample_first_100000_rows |
| shareswa | BIGINT | 1555 | 1.555 | sample_first_100000_rows |
| shareswadil | BIGINT | 34090 | 34.09 | sample_first_100000_rows |
| sps | DOUBLE | 5979 | 5.979 | sample_first_100000_rows |
| tangibles | BIGINT | 3243 | 3.243 | sample_first_100000_rows |
| taxassets | BIGINT | 3215 | 3.215 | sample_first_100000_rows |
| taxexp | BIGINT | 5002 | 5.002 | sample_first_100000_rows |
| taxliabilities | BIGINT | 3199 | 3.199 | sample_first_100000_rows |
| tbvps | DOUBLE | 3999 | 3.999 | sample_first_100000_rows |
| workingcapital | BIGINT | 17084 | 17.084 | sample_first_100000_rows |

### First 5 Rows

| ticker | dimension | calendardate | datekey | reportperiod | fiscalperiod | lastupdated | accoci | assets | assetsavg | assetsc | assetsnc | assetturnover | bvps | capex | cashneq | cashnequsd | cor | consolinc | currentratio | de | debt | debtc | debtnc | debtusd | deferredrev | depamor | deposits | divyield | dps | ebit | ebitda | ebitdamargin | ebitdausd | ebitusd | ebt | eps | epsdil | epsusd | equity | equityavg | equityusd | ev | evebit | evebitda | fcf | fcfps | fxusd | gp | grossmargin | intangibles | intexp | invcap | invcapavg | inventory | investments | investmentsc | investmentsnc | liabilities | liabilitiesc | liabilitiesnc | marketcap | ncf | ncfbus | ncfcommon | ncfdebt | ncfdiv | ncff | ncfi | ncfinv | ncfo | ncfx | netinc | netinccmn | netinccmnusd | netincdis | netincnci | netmargin | opex | opinc | payables | payoutratio | pb | pe | pe1 | ppnenet | prefdivis | price | ps | ps1 | receivables | retearn | revenue | revenueusd | rnd | roa | roe | roic | ros | sbcomp | sgna | sharefactor | sharesbas | shareswa | shareswadil | sps | tangibles | taxassets | taxexp | taxliabilities | tbvps | workingcapital |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADGI1 | MRT | 2006-06-30 | 2006-06-30 | 2006-06-30 | 2006-Q2 | 2024-04-22 | 14935000 | 191889000 | 182798750 | 121434000 | 70455000 | 0.694 | 12.77 | -6911000 | 28428000 | 28428000 | 106486000 | -37731000 | 1.553 | 1.489 | 54138000 | 19391000 | 34747000 | 54138000 | 0 | 6225000 | 20278000 | 0.0 | 0.0 | -28241000 | -22016000 | -0.174 | -22016000 | -28241000 | -33487000 | -6.43 | -6.43 | -6.43 | 77094000 | 85954500 | 77094000 | 121205103 | -4 | -5.505 | -17168000 | -2.844 | 1.0 | 20325000 | 0.16 | 29647000 | 5246000 | 109739000 | 101770000 | 32945000 | 0 | 0 | 0 | 114795000 | 78213000 | 36582000 | 128458103 | 7416000 | -9616000 | 2947000 | 31466000 | 0 | 34413000 | -16532000 | 0 | -10257000 | -698000 | -37731000 | -37731000 | -37731000 | 796000 | 0 | -0.298 | 48439000 | -28114000 | 23402000 | 0.0 | 1.666 | -3.405 | -3.42 | 32329000 | 0 | 21.99 | 1.013 | 1.047 | 50323000 | 25722000 | 126811000 | 126811000 | 7582000 | -0.206 | -0.439 | -0.277 | -0.223 | 851000 | 37797000 | 1.0 | 5841660 | 6037280 | 6037280 | 21.005 | 162242000 | 8867000 | 4244000 | 866000 | 26.873 | 43221000 |
| ADGI1 | MRQ | 2006-03-31 | 2006-03-31 | 2006-03-31 | 2006-Q1 | 2024-04-22 | 13091000 | 204787000 |  | 135927000 | 68860000 |  | 13.278 | -1062000 | 34123000 | 34123000 | 26431000 | -3711000 | 1.55 | 1.562 | 61919000 | 26782000 | 35137000 | 61919000 | 0 | 1523000 | 19770000 | 0.0 | 0.0 | -1400000 | 123000 | 0.004 | 123000 | -1400000 | -3713000 | -0.62 | -0.62 | -0.62 | 79933000 |  | 79933000 | 120971437 | -5 | -6.2 | 269000 | 0.045 | 1.0 | 8274000 | 0.238 | 29837000 | 2313000 | 115025000 |  | 33464000 | 0 | 0 | 0 | 124854000 | 87721000 | 37133000 | 128224437 | 20985000 | 0 | 411000 | 19991000 | 0 | 20402000 | -1070000 | 0 | 1331000 | 162000 | -3711000 | -3711000 | -3711000 | 585000 | 0 | -0.107 | 10122000 | -1848000 | 20980000 | 0.0 | 1.604 | -3.839 | -3.837 | 30475000 | 0 | 21.95 | 1.043 | 1.075 | 57971000 | 30755000 | 34705000 | 34705000 | 1550000 |  |  |  |  | 330000 | 8572000 | 1.0 | 5841660 | 6020149 | 6020149 | 5.765 | 174950000 | 8676000 | -2000 | 1128000 | 29.061 | 48206000 |
| ADGI1 | MRT | 2006-03-31 | 2006-03-31 | 2006-03-31 | 2006-Q1 | 2024-04-22 | 13091000 | 204787000 | 172256000 | 135927000 | 68860000 | 0.714 | 13.278 | -8226000 | 34123000 | 34123000 | 100668000 | -33398000 | 1.55 | 1.562 | 61919000 | 26782000 | 35137000 | 61919000 | 0 | 6340000 | 19770000 | 0.0 | 0.0 | -25853000 | -19513000 | -0.159 | -19513000 | -25853000 | -30196000 | -5.72 | -5.72 | -5.72 | 79933000 | 94449750 | 79933000 | 120971437 | -5 | -6.2 | -34987000 | -5.812 | 1.0 | 22241000 | 0.181 | 29837000 | 4343000 | 115025000 | 95491750 | 33464000 | 0 | 0 | 0 | 124854000 | 87721000 | 37133000 | 128224437 | 254000 | -9443000 | 3036000 | 41785000 | 0 | 44821000 | -17677000 | 0 | -26761000 | 1298000 | -33398000 | -33398000 | -33398000 | 585000 | 0 | -0.272 | 47808000 | -25567000 | 20980000 | 0.0 | 1.604 | -3.839 | -3.837 | 30475000 | 0 | 21.95 | 1.043 | 1.075 | 57971000 | 30755000 | 122909000 | 122909000 | 7213000 | -0.194 | -0.354 | -0.271 | -0.21 | 955000 | 37535000 | 1.0 | 5841660 | 6020149 | 6020149 | 20.416 | 174950000 | 8676000 | 3202000 | 1128000 | 29.061 | 48206000 |
| ADGI1 | MRQ | 2005-12-31 | 2005-12-31 | 2005-12-31 | 2005-Q4 | 2024-04-22 | 12075000 | 180946000 |  | 114296000 | 66650000 |  | 13.519 | -2707000 | 15231000 | 15231000 | 28989000 | -22321000 | 1.467 | 1.22 | 40787000 | 19428000 | 21359000 | 40787000 | 0 | 2358000 | 9956000 | 0.0 | 0.0 | -14587000 | -12229000 | -0.347 | -12229000 | -14587000 | -15714000 | -3.83 | -3.83 | -3.83 | 81493000 |  | 81493000 | 125761598 | -4 | -4.305 | 997000 | 0.165 | 1.0 | 6238000 | 0.177 | 30051000 | 1127000 | 98517000 |  | 34300000 | 0 | 0 | 0 | 99453000 | 77934000 | 21519000 | 133014598 | -2477000 | -9443000 | 45000 | 6375000 | 0 | 6420000 | -12150000 | 0 | 3704000 | 1859000 | -22321000 | -22321000 | -22321000 | 0 | 0 | -0.634 | 19125000 | -12887000 | 31004000 | 0.0 | 1.632 | -3.418 | -3.368 | 29826000 | 0 | 22.77 | 1.185 | 1.168 | 53725000 | 34466000 | 35227000 | 35227000 | 2845000 |  |  |  |  | 467000 | 13220000 | 1.0 | 5841660 | 6028236 | 6028236 | 5.844 | 150895000 | 8368000 | 6607000 | 1288000 | 25.031 | 36362000 |
| ADGI1 | MRT | 2005-12-31 | 2005-12-31 | 2005-12-31 | 2005-Q4 | 2024-04-22 | 12075000 | 180946000 | 161115250 | 114296000 | 66650000 | 0.697 | 14.161 | -8167000 | 15231000 | 15231000 | 94154000 | -38920000 | 1.467 | 1.22 | 40787000 | 19428000 | 21359000 | 40787000 | 0 | 6082000 | 9956000 | 0.0 | 0.0 | -35292000 | -29210000 | -0.26 | -29210000 | -35292000 | -37860000 | -6.76 | -6.76 | -6.76 | 81493000 | 105035000 | 81493000 | 125761598 | -4 | -4.305 | -30396000 | -5.282 | 1.0 | 18068000 | 0.161 | 30051000 | 2568000 | 98517000 | 86452500 | 34300000 | 0 | 0 | 0 | 99453000 | 77934000 | 21519000 | 133014598 | -20137000 | -9443000 | 2800000 | 17353000 | 0 | 20153000 | -17610000 | 0 | -22229000 | -451000 | -38920000 | -38920000 | -38920000 | 0 | 0 | -0.347 | 46721000 | -28653000 | 31004000 | 0.0 | 1.632 | -3.418 | -3.368 | 29826000 | 0 | 22.77 | 1.185 | 1.168 | 53725000 | 34466000 | 112222000 | 112222000 | 7190000 | -0.242 | -0.371 | -0.408 | -0.314 | 694000 | 36471000 | 1.0 | 5841660 | 5754951 | 5754951 | 19.5 | 150895000 | 8368000 | 1060000 | 1288000 | 26.22 | 36362000 |

### Last 5 Rows

_Skipped in fast mode or not inexpensive for this table._

### Date Coverage

**calendardate**
- `min_date`: 1991-06-30
- `max_date`: 2026-12-31
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**datekey**
- `min_date`: 1991-06-29
- `max_date`: 2026-08-12
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**reportperiod**
- `min_date`: 1991-06-29
- `max_date`: 2026-07-04
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**fiscalperiod**
- `min_date`: 
- `max_date`: 
- `parsed_rows`: 0
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**lastupdated**
- `min_date`: 2018-09-09
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 1669
- `scope`: sample_first_100000_rows
**dimension**
- `column`: dimension
- `distinct_count`: 6
- `scope`: sample_first_100000_rows

### Categorical Values

**dimension**
| value | row_count |
| --- | --- |
| MRT | 22649 |
| ARQ | 22076 |
| MRQ | 22015 |
| ART | 21508 |
| MRY | 6126 |
| ARY | 5626 |

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'dimension', 'calendardate', 'datekey', 'reportperiod'] | sample_first_100000_rows |
| 0 | 0 | ['ticker', 'dimension', 'datekey'] | sample_first_100000_rows |

### Table-Specific Checks

**dimensions_available**
| value | row_count |
| --- | --- |
| MRT | 22659 |
| MRQ | 22209 |
| ARQ | 22068 |
| ART | 21265 |
| MRY | 6137 |
| ARY | 5662 |
**dimension_example_rows**
**ARQ**
| ticker | dimension | calendardate | datekey | reportperiod | fiscalperiod | lastupdated | accoci | assets | assetsavg | assetsc | assetsnc | assetturnover | bvps | capex | cashneq | cashnequsd | cor | consolinc | currentratio | de | debt | debtc | debtnc | debtusd | deferredrev | depamor | deposits | divyield | dps | ebit | ebitda | ebitdamargin | ebitdausd | ebitusd | ebt | eps | epsdil | epsusd | equity | equityavg | equityusd | ev | evebit | evebitda | fcf | fcfps | fxusd | gp | grossmargin | intangibles | intexp | invcap | invcapavg | inventory | investments | investmentsc | investmentsnc | liabilities | liabilitiesc | liabilitiesnc | marketcap | ncf | ncfbus | ncfcommon | ncfdebt | ncfdiv | ncff | ncfi | ncfinv | ncfo | ncfx | netinc | netinccmn | netinccmnusd | netincdis | netincnci | netmargin | opex | opinc | payables | payoutratio | pb | pe | pe1 | ppnenet | prefdivis | price | ps | ps1 | receivables | retearn | revenue | revenueusd | rnd | roa | roe | roic | ros | sbcomp | sgna | sharefactor | sharesbas | shareswa | shareswadil | sps | tangibles | taxassets | taxexp | taxliabilities | tbvps | workingcapital |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KTII | ARQ | 2009-12-31 | 2010-03-15 | 2010-01-02 | 2009-Q4 | 2023-07-19 | 13543000 | 204236000 |  | 121618000 | 82618000 |  | 54.059 | -264000 | 62915000 | 62915000 | 23504000 | 5082000 | 3.029 | 0.332 | 8000000 | 1000000 | 7000000 | 8000000 | 0 | 1408000 | 6820000 | 0.0 | 0.0 | 6783000 | 8191000 | 0.187 | 8191000 | 6783000 | 6693000 | 1.79 | 1.75 | 1.79 | 153312000 |  | 153312000 | 370386842 | 11 | 9.528 | 5665000 | 1.998 | 1.0 | 20226000 | 0.463 | 52009000 | 90000 | 57163000 |  | 26359000 | 0 | 0 | 0 | 50924000 | 40149000 | 10775000 | 425301842 | 75000 | 0 | 0 | -10000000 | 0 | -9241000 | 3414000 | 0 | 5929000 | -27000 | 5082000 | 5082000 | 5082000 | 0 | 0 | 0.116 | 13443000 | 6783000 | 10767000 | 0.0 | 2.774 | 19.731 | 19.589 | 23926000 | 0 | 149.66 | 2.229 | 2.213 | 25878000 | 137904000 | 43730000 | 43730000 | 482000 |  |  |  |  | 189000 | 12961000 | 1.0 | 2841787 | 2836000 | 2897000 | 15.42 | 152227000 | 4209000 | 1611000 | 10630000 | 53.677 | 81469000 |
| KTII | ARQ | 2009-09-30 | 2009-11-10 | 2009-10-03 | 2009-Q3 | 2023-07-19 | 12863000 | 205886000 |  | 123381000 | 82505000 |  | 51.851 | -751000 | 63001000 | 63001000 | 27438000 | 6768000 | 3.292 | 0.403 | 18000000 | 1000000 | 17000000 | 18000000 | 0 | 1542000 | 8230000 | 0.0 | 0.0 | 10660000 | 12202000 | 0.258 | 12202000 | 10660000 | 10408000 | 2.39 | 2.34 | 2.39 | 146789000 |  | 146789000 | 257063258 | 7 | 6.15 | 13115000 | 4.633 | 1.0 | 19883000 | 0.42 | 52256000 | 252000 | 71150000 |  | 23678000 | 0 | 0 | 0 | 59097000 | 37479000 | 21618000 | 302064258 | 13389000 | 0 | -239000 | -2000000 | 0 | -1964000 | -737000 | 0 | 13866000 | 2224000 | 6768000 | 6768000 | 6768000 | 0 | 0 | 0.143 | 12195000 | 7688000 | 9883000 | 0.0 | 2.058 | 13.324 | 13.17 | 24799000 | 0 | 106.41 | 1.419 | 1.415 | 26735000 | 132822000 | 47321000 | 47321000 | 439000 |  |  |  |  | 50000 | 11756000 | 1.0 | 2838683 | 2831000 | 2887000 | 16.715 | 153630000 | 2718000 | 3640000 | 9955000 | 54.267 | 85902000 |
| KTII | ARQ | 2009-06-30 | 2009-08-10 | 2009-07-04 | 2009-Q2 | 2023-07-19 | 9716000 | 196612000 |  | 113086000 | 83526000 |  | 48.74 | -433000 | 49644000 | 49644000 | 29032000 | 5258000 | 3.174 | 0.432 | 20000000 | 1000000 | 19000000 | 20000000 | 0 | 1503000 | 7795000 | 0.0 | 0.0 | 8436000 | 9939000 | 0.199 | 9939000 | 8436000 | 8154000 | 1.87 | 1.82 | 1.87 | 137251000 |  | 137251000 | 225984686 | 7 | 5.575 | 8027000 | 2.85 | 1.0 | 21005000 | 0.42 | 51515000 | 282000 | 79824000 |  | 25580000 | 0 | 0 | 0 | 59361000 | 35629000 | 23732000 | 255628686 | 6531000 | 0 | -555000 | -2602000 | 0 | -2862000 | -460000 | 0 | 8460000 | 1393000 | 5258000 | 5258000 | 5258000 | 0 | 0 | 0.105 | 12569000 | 8436000 | 9443000 | 0.0 | 1.862 | 11.277 | 11.102 | 24940000 | 0 | 90.26 | 1.135 | 1.129 | 30532000 | 126054000 | 50037000 | 50037000 | 387000 |  |  |  |  | 184000 | 12182000 | 1.0 | 2832137 | 2816000 | 2891000 | 17.769 | 145097000 | 2718000 | 2896000 | 9780000 | 51.526 | 77457000 |
**ART**
| ticker | dimension | calendardate | datekey | reportperiod | fiscalperiod | lastupdated | accoci | assets | assetsavg | assetsc | assetsnc | assetturnover | bvps | capex | cashneq | cashnequsd | cor | consolinc | currentratio | de | debt | debtc | debtnc | debtusd | deferredrev | depamor | deposits | divyield | dps | ebit | ebitda | ebitdamargin | ebitdausd | ebitusd | ebt | eps | epsdil | epsusd | equity | equityavg | equityusd | ev | evebit | evebitda | fcf | fcfps | fxusd | gp | grossmargin | intangibles | intexp | invcap | invcapavg | inventory | investments | investmentsc | investmentsnc | liabilities | liabilitiesc | liabilitiesnc | marketcap | ncf | ncfbus | ncfcommon | ncfdebt | ncfdiv | ncff | ncfi | ncfinv | ncfo | ncfx | netinc | netinccmn | netinccmnusd | netincdis | netincnci | netmargin | opex | opinc | payables | payoutratio | pb | pe | pe1 | ppnenet | prefdivis | price | ps | ps1 | receivables | retearn | revenue | revenueusd | rnd | roa | roe | roic | ros | sbcomp | sgna | sharefactor | sharesbas | shareswa | shareswadil | sps | tangibles | taxassets | taxexp | taxliabilities | tbvps | workingcapital |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KTII | ART | 2009-12-31 | 2010-03-15 | 2010-01-02 | 2009-Q4 | 2023-07-19 | 13543000 | 204236000 | 199948750 | 121618000 | 82618000 | 0.954 | 54.347 | -1820000 | 62915000 | 62915000 | 109502000 | 21555000 | 3.029 | 0.332 | 8000000 | 1000000 | 7000000 | 8000000 | 0 | 6023000 | 6820000 | 0.0 | 0.0 | 32852000 | 38875000 | 0.204 | 38875000 | 32852000 | 31916000 | 7.64 | 7.5 | 7.64 | 153312000 | 141609750 | 153312000 | 370386842 | 11 | 9.528 | 29765000 | 10.551 | 1.0 | 81272000 | 0.426 | 52009000 | 936000 | 57163000 | 72612000 | 26359000 | 0 | 0 | 0 | 50924000 | 40149000 | 10775000 | 425301842 | 21000000 | 0 | -524000 | -15662000 | 0 | -14624000 | 1876000 | 0 | 31585000 | 2163000 | 21555000 | 21555000 | 21555000 | 0 | 0 | 0.113 | 51392000 | 29880000 | 10767000 | 0.0 | 2.774 | 19.731 | 19.589 | 23926000 | 0 | 149.66 | 2.229 | 2.213 | 25878000 | 137904000 | 190774000 | 190774000 | 1871000 | 0.108 | 0.152 | 0.452 | 0.172 | 613000 | 49521000 | 1.0 | 2841787 | 2821000 | 2873000 | 67.626 | 152227000 | 4209000 | 10361000 | 10630000 | 53.962 | 81469000 |
| KTII | ART | 2009-09-30 | 2009-11-10 | 2009-10-03 | 2009-Q3 | 2023-07-19 | 12863000 | 205886000 | 198750750 | 123381000 | 82505000 | 1.071 | 51.851 | -2669000 | 63001000 | 63001000 | 124909000 | 22670000 | 3.292 | 0.403 | 18000000 | 1000000 | 17000000 | 18000000 | 0 | 6000000 | 8230000 | 0.0 | 0.0 | 35797000 | 41797000 | 0.196 | 41797000 | 35797000 | 34762000 | 8.08 | 7.89 | 8.08 | 146789000 | 134794750 | 146789000 | 257063258 | 7 | 6.15 | 33951000 | 11.993 | 1.0 | 87914000 | 0.413 | 52256000 | 1035000 | 71150000 | 78925750 | 23678000 | 0 | 0 | 0 | 59097000 | 37479000 | 21618000 | 302064258 | 29315000 | 0 | -222000 | -7722000 | 0 | -6569000 | -2684000 | 0 | 36620000 | 1948000 | 22670000 | 22670000 | 22670000 | 0 | 0 | 0.107 | 55089000 | 32825000 | 9883000 | 0.0 | 2.058 | 13.324 | 13.17 | 24799000 | 0 | 106.41 | 1.419 | 1.415 | 26735000 | 132822000 | 212823000 | 212823000 | 1958000 | 0.114 | 0.168 | 0.454 | 0.168 | 615000 | 53131000 | 1.0 | 2838683 | 2831000 | 2887000 | 75.176 | 153630000 | 2718000 | 12092000 | 9955000 | 54.267 | 85902000 |
| KTII | ART | 2009-06-30 | 2009-08-10 | 2009-07-04 | 2009-Q2 | 2023-07-19 | 9716000 | 196612000 | 195833250 | 113086000 | 83526000 | 1.15 | 48.74 | -2680000 | 49644000 | 49644000 | 132318000 | 22669000 | 3.174 | 0.432 | 20000000 | 1000000 | 19000000 | 20000000 | 0 | 5934000 | 7795000 | 0.0 | 0.0 | 34599000 | 40533000 | 0.18 | 40533000 | 34599000 | 33637000 | 8.13 | 7.89 | 8.13 | 137251000 | 127225500 | 137251000 | 225984686 | 7 | 5.575 | 22048000 | 7.83 | 1.0 | 92815000 | 0.412 | 51515000 | 962000 | 79824000 | 82312750 | 25580000 | 0 | 0 | 0 | 59361000 | 35629000 | 23732000 | 255628686 | 13015000 | 100000 | 44000 | -7923000 | 0 | -6754000 | -2577000 | 0 | 24728000 | -2382000 | 22669000 | 22669000 | 22669000 | 0 | 0 | 0.101 | 58216000 | 34599000 | 9443000 | 0.0 | 1.862 | 11.277 | 11.102 | 24940000 | 0 | 90.26 | 1.135 | 1.129 | 30532000 | 126054000 | 225133000 | 225133000 | 2152000 | 0.116 | 0.178 | 0.42 | 0.154 | 748000 | 56064000 | 1.0 | 2832137 | 2816000 | 2891000 | 79.948 | 145097000 | 2718000 | 10968000 | 9780000 | 51.526 | 77457000 |
**MRY**
| ticker | dimension | calendardate | datekey | reportperiod | fiscalperiod | lastupdated | accoci | assets | assetsavg | assetsc | assetsnc | assetturnover | bvps | capex | cashneq | cashnequsd | cor | consolinc | currentratio | de | debt | debtc | debtnc | debtusd | deferredrev | depamor | deposits | divyield | dps | ebit | ebitda | ebitdamargin | ebitdausd | ebitusd | ebt | eps | epsdil | epsusd | equity | equityavg | equityusd | ev | evebit | evebitda | fcf | fcfps | fxusd | gp | grossmargin | intangibles | intexp | invcap | invcapavg | inventory | investments | investmentsc | investmentsnc | liabilities | liabilitiesc | liabilitiesnc | marketcap | ncf | ncfbus | ncfcommon | ncfdebt | ncfdiv | ncff | ncfi | ncfinv | ncfo | ncfx | netinc | netinccmn | netinccmnusd | netincdis | netincnci | netmargin | opex | opinc | payables | payoutratio | pb | pe | pe1 | ppnenet | prefdivis | price | ps | ps1 | receivables | retearn | revenue | revenueusd | rnd | roa | roe | roic | ros | sbcomp | sgna | sharefactor | sharesbas | shareswa | shareswadil | sps | tangibles | taxassets | taxexp | taxliabilities | tbvps | workingcapital |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADGI1 | MRY | 2005-12-31 | 2005-12-31 | 2005-12-31 | 2005-FY | 2024-04-22 | 12075000 | 180946000 | 161115250 | 114296000 | 66650000 | 0.697 | 14.161 | -8167000 | 15231000 | 15231000 | 94154000 | -38920000 | 1.467 | 1.22 | 40787000 | 19428000 | 21359000 | 40787000 | 0 | 6082000 | 9956000 | 0.0 | 0.0 | -35292000 | -29210000 | -0.26 | -29210000 | -35292000 | -37860000 | -6.76 | -6.76 | -6.76 | 81493000 | 105035000 | 81493000 | 125761598 | -4 | -4.305 | -30396000 | -5.282 | 1.0 | 18068000 | 0.161 | 30051000 | 2568000 | 98517000 | 86452500 | 34300000 | 0 | 0 | 0 | 99453000 | 77934000 | 21519000 | 133014598 | -20137000 | -9443000 | 2800000 | 17353000 | 0 | 20153000 | -17610000 | 0 | -22229000 | -451000 | -38920000 | -38920000 | -38920000 | 0 | 0 | -0.347 | 46721000 | -28653000 | 31004000 | 0.0 | 1.632 | -3.418 | -3.368 | 29826000 | 0 | 22.77 | 1.185 | 1.168 | 53725000 | 34466000 | 112222000 | 112222000 | 7190000 | -0.242 | -0.371 | -0.408 | -0.314 | 694000 | 36471000 | 1.0 | 5841660 | 5754951 | 5754951 | 19.5 | 150895000 | 8368000 | 1060000 | 1288000 | 26.22 | 36362000 |
| ADGI1 | MRY | 2004-12-31 | 2004-12-31 | 2004-12-31 | 2004-FY | 2024-04-22 | 23697000 | 192231000 | 203132500 | 138041000 | 54190000 | 0.72 | 22.548 | -4991000 | 39179000 | 39179000 | 105819000 | 1370000 | 2.337 | 0.531 | 17795000 | 10572000 | 7223000 | 17795000 | 0 | 4551000 | 8662000 | 0.0 | 0.0 | 4120000 | 8671000 | 0.059 | 8671000 | 4120000 | 1679000 | 0.25 | 0.24 | 0.25 | 125553000 | 117368250 | 125553000 | 117312478 | 28 | 13.529 | 4413000 | 0.793 | 1.0 | 40382000 | 0.276 | 18124000 | 2441000 | 93645000 | 94963000 | 17128000 | 0 | 0 | 0 | 66678000 | 59078000 | 7600000 | 124591478 | -15437000 | -525000 | 609000 | -19559000 | 0 | -20950000 | -5516000 | 0 | 9404000 | 1625000 | 1370000 | 1370000 | 1370000 | 0 | 0 | 0.009 | 36300000 | 4082000 | 26661000 | 0.0 | 0.992 | 90.943 | 89.0 | 30294000 | 0 | 22.25 | 0.852 | 0.847 | 76400000 | 73386000 | 146201000 | 146201000 | 6695000 | 0.007 | 0.012 | 0.043 | 0.028 | 538000 | 29605000 | 1.0 | 5599617 | 5568183 | 5745282 | 26.257 | 174107000 | 4477000 | 309000 | 811000 | 31.268 | 78963000 |
| ADGI1 | MRY | 2003-12-31 | 2003-12-31 | 2003-12-31 | 2003-FY | 2024-04-22 | 15636000 | 217331000 | 203067250 | 174485000 | 42846000 | 0.757 | 21.058 | -4353000 | 59314000 | 59314000 | 114904000 | 2718000 | 1.963 | 0.878 | 29217000 | 22159000 | 7058000 | 29217000 | 0 | 4036000 | 4938000 | 0.0 | 0.0 | 9865000 | 13901000 | 0.09 | 13901000 | 9865000 | 7374000 | 0.49 | 0.48 | 0.49 | 115753000 | 102595250 | 115753000 | 119496782 | 12 | 8.596 | 20414000 | 3.714 | 1.0 | 38870000 | 0.253 | 17853000 | 2491000 | 80500000 | 78313500 | 12068000 | 0 | 0 | 0 | 101578000 | 88881000 | 12697000 | 131645782 | 28501000 | 0 | 916000 | 3165000 | 0 | 4081000 | -4353000 | 0 | 24767000 | 4006000 | 2718000 | 2718000 | 2718000 | 0 | 0 | 0.018 | 28981000 | 9889000 | 53284000 | 0.0 | 1.137 | 48.435 | 48.796 | 24615000 | 0 | 23.91 | 0.856 | 0.855 | 90307000 | 73671000 | 153774000 | 153774000 | 4532000 | 0.013 | 0.026 | 0.126 | 0.064 | 562000 | 24449000 | 1.0 | 5505888 | 5496786 | 5670119 | 27.975 | 199478000 | 1016000 | 4656000 | 5211000 | 36.29 | 85604000 |
**MRT**
| ticker | dimension | calendardate | datekey | reportperiod | fiscalperiod | lastupdated | accoci | assets | assetsavg | assetsc | assetsnc | assetturnover | bvps | capex | cashneq | cashnequsd | cor | consolinc | currentratio | de | debt | debtc | debtnc | debtusd | deferredrev | depamor | deposits | divyield | dps | ebit | ebitda | ebitdamargin | ebitdausd | ebitusd | ebt | eps | epsdil | epsusd | equity | equityavg | equityusd | ev | evebit | evebitda | fcf | fcfps | fxusd | gp | grossmargin | intangibles | intexp | invcap | invcapavg | inventory | investments | investmentsc | investmentsnc | liabilities | liabilitiesc | liabilitiesnc | marketcap | ncf | ncfbus | ncfcommon | ncfdebt | ncfdiv | ncff | ncfi | ncfinv | ncfo | ncfx | netinc | netinccmn | netinccmnusd | netincdis | netincnci | netmargin | opex | opinc | payables | payoutratio | pb | pe | pe1 | ppnenet | prefdivis | price | ps | ps1 | receivables | retearn | revenue | revenueusd | rnd | roa | roe | roic | ros | sbcomp | sgna | sharefactor | sharesbas | shareswa | shareswadil | sps | tangibles | taxassets | taxexp | taxliabilities | tbvps | workingcapital |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KTII | MRT | 2009-12-31 | 2010-01-02 | 2010-01-02 | 2009-Q4 | 2023-07-19 | 13543000 | 204236000 | 199948750 | 121618000 | 82618000 | 0.954 | 54.347 | -1820000 | 62915000 | 62915000 | 109502000 | 21555000 | 3.029 | 0.332 | 8000000 | 1000000 | 7000000 | 8000000 | 0 | 6023000 | 6820000 | 0.0 | 0.0 | 32852000 | 38875000 | 0.204 | 38875000 | 32852000 | 31916000 | 7.64 | 7.5 | 7.64 | 153312000 | 141609750 | 153312000 | 263705776 | 8 | 6.783 | 29765000 | 10.551 | 1.0 | 81272000 | 0.426 | 52009000 | 936000 | 57163000 | 72612000 | 26359000 | 0 | 0 | 0 | 50924000 | 40149000 | 10775000 | 308706776 | 21000000 | 0 | -524000 | -15662000 | 0 | -14624000 | 1876000 | 0 | 31585000 | 2163000 | 21555000 | 21555000 | 21555000 | 0 | 0 | 0.113 | 51392000 | 29880000 | 10767000 | 0.0 | 2.014 | 14.322 | 14.234 | 23926000 | 0 | 108.75 | 1.618 | 1.608 | 25878000 | 137904000 | 190774000 | 190774000 | 1871000 | 0.108 | 0.152 | 0.452 | 0.172 | 613000 | 49521000 | 1.0 | 2838683 | 2821000 | 2873000 | 67.626 | 152227000 | 4209000 | 10361000 | 10630000 | 53.962 | 81469000 |
| KTII | MRT | 2009-09-30 | 2009-10-03 | 2009-10-03 | 2009-Q3 | 2023-07-19 | 12863000 | 205886000 | 198750750 | 123381000 | 82505000 | 1.071 | 51.851 | -2669000 | 63001000 | 63001000 | 124909000 | 22670000 | 3.292 | 0.403 | 18000000 | 1000000 | 17000000 | 18000000 | 0 | 6000000 | 8230000 | 0.0 | 0.0 | 35797000 | 41797000 | 0.196 | 41797000 | 35797000 | 34762000 | 8.08 | 7.89 | 8.08 | 146789000 | 134794750 | 146789000 | 236548557 | 7 | 5.659 | 33951000 | 11.993 | 1.0 | 87914000 | 0.413 | 52256000 | 1035000 | 71150000 | 78925750 | 23678000 | 0 | 0 | 0 | 59097000 | 37479000 | 21618000 | 266192557 | 29315000 | 0 | -222000 | -7722000 | 0 | -6569000 | -2684000 | 0 | 36620000 | 1948000 | 22670000 | 22670000 | 22670000 | 0 | 0 | 0.107 | 55089000 | 32825000 | 9883000 | 0.0 | 1.813 | 11.742 | 11.632 | 24799000 | 0 | 93.99 | 1.251 | 1.25 | 26735000 | 132822000 | 212823000 | 212823000 | 1958000 | 0.114 | 0.168 | 0.454 | 0.168 | 615000 | 53131000 | 1.0 | 2832137 | 2831000 | 2887000 | 75.176 | 153630000 | 2718000 | 12092000 | 9955000 | 54.267 | 85902000 |
| KTII | MRT | 2009-06-30 | 2009-07-04 | 2009-07-04 | 2009-Q2 | 2023-07-19 | 9716000 | 196612000 | 195833250 | 113086000 | 83526000 | 1.15 | 48.74 | -2680000 | 49644000 | 49644000 | 132318000 | 22669000 | 3.174 | 0.432 | 20000000 | 1000000 | 19000000 | 20000000 | 0 | 5934000 | 7795000 | 0.0 | 0.0 | 34599000 | 40533000 | 0.18 | 40533000 | 34599000 | 33637000 | 8.13 | 7.89 | 8.13 | 137251000 | 127225500 | 137251000 | 203888593 | 6 | 5.03 | 22048000 | 7.83 | 1.0 | 92815000 | 0.412 | 51515000 | 962000 | 79824000 | 82312750 | 25580000 | 0 | 0 | 0 | 59361000 | 35629000 | 23732000 | 224399593 | 13015000 | 100000 | 44000 | -7923000 | 0 | -6754000 | -2577000 | 0 | 24728000 | -2382000 | 22669000 | 22669000 | 22669000 | 0 | 0 | 0.101 | 58216000 | 34599000 | 9443000 | 0.0 | 1.635 | 9.899 | 9.809 | 24940000 | 0 | 79.75 | 0.997 | 0.998 | 30532000 | 126054000 | 225133000 | 225133000 | 2152000 | 0.116 | 0.178 | 0.42 | 0.154 | 748000 | 56064000 | 1.0 | 2813788 | 2816000 | 2891000 | 79.948 | 145097000 | 2718000 | 10968000 | 9780000 | 51.526 | 77457000 |
**date_fields**
**calendardate**
- `min_date`: 1991-06-30
- `max_date`: 2026-12-31
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**datekey**
- `min_date`: 1991-06-29
- `max_date`: 2026-08-12
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**reportperiod**
- `min_date`: 1991-06-29
- `max_date`: 2026-07-04
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**fiscalperiod**
- `min_date`: 
- `max_date`: 
- `parsed_rows`: 0
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**lastupdated**
- `min_date`: 2018-09-09
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**identifier_fields**
- `ticker`
**unique_tickers**
- `column`: ticker
- `distinct_count`: 1631
- `scope`: sample_first_100000_rows

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SF1_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.062 |
| duckdb_view_and_schema | 1.011 |
| example_rows | 0.538 |
| row_count | 0.011 |
| null_profile | 1.67 |
| date_ranges | 2.745 |
| distincts_and_categories | 1.621 |
| duplicate_key_checks | 1.088 |
| table_specific_checks | 5.892 |
| sample_csv | 0.569 |

## SF2

File: `SHARADAR_SF2_2_8a47be226448a026901c826d1420881c.csv`
Size: `1183649169` bytes (`1.10 GB`)
Rows: `~11,505,520`
Columns: `24`
Elapsed: `2.05s`

### Issues And Warnings

- Warning: Row count is estimated in default mode; run with --full-profile for exact DuckDB count.
- Warning: Null counts and percentages are sample-based in default mode for large tables.
- Warning: Duplicate key checks are sample-based in default mode for this table.

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| filingdate | DATE | 0 | 0.0 | sample_first_100000_rows |
| formtype | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| issuername | VARCHAR | 100000 | 100.0 | sample_first_100000_rows |
| ownername | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| officertitle | VARCHAR | 34558 | 34.558 | sample_first_100000_rows |
| isdirector | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| isofficer | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| istenpercentowner | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| transactiondate | DATE | 24459 | 24.459 | sample_first_100000_rows |
| securityadcode | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| transactioncode | VARCHAR | 24462 | 24.462 | sample_first_100000_rows |
| sharesownedbeforetransaction | BIGINT | 14 | 0.014 | sample_first_100000_rows |
| transactionshares | BIGINT | 0 | 0.0 | sample_first_100000_rows |
| sharesownedfollowingtransaction | BIGINT | 14 | 0.014 | sample_first_100000_rows |
| transactionpricepershare | DOUBLE | 39315 | 39.315 | sample_first_100000_rows |
| transactionvalue | BIGINT | 54171 | 54.171 | sample_first_100000_rows |
| securitytitle | VARCHAR | 1044 | 1.044 | sample_first_100000_rows |
| directorindirect | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| natureofownership | VARCHAR | 78867 | 78.867 | sample_first_100000_rows |
| dateexercisable | DATE | 94208 | 94.208 | sample_first_100000_rows |
| priceexercisable | DOUBLE | 86084 | 86.084 | sample_first_100000_rows |
| expirationdate | DATE | 87519 | 87.519 | sample_first_100000_rows |
| rownum | BIGINT | 0 | 0.0 | sample_first_100000_rows |

### First 5 Rows

| ticker | filingdate | formtype | issuername | ownername | officertitle | isdirector | isofficer | istenpercentowner | transactiondate | securityadcode | transactioncode | sharesownedbeforetransaction | transactionshares | sharesownedfollowingtransaction | transactionpricepershare | transactionvalue | securitytitle | directorindirect | natureofownership | dateexercisable | priceexercisable | expirationdate | rownum |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| API | 2026-06-10 | 3 |  | ZHAO BIN | CEO | Y | Y | N |  | D |  | 2250000 | 0 | 2250000 |  |  | ISO | D |  |  | 4.5 | 2035-09-03 | 4 |
| API | 2026-06-10 | 3 |  | ZHAO BIN | CEO | Y | Y | N |  | D |  | 2250000 | 0 | 2250000 |  |  | RSU | D |  |  | 0.0 | 2035-09-03 | 5 |
| GDRX | 2026-06-10 | 4 |  | BEZDEK TREVOR |  | Y | N | N | 2026-06-08 | NA | A | 160082 | 110294 | 270376 | 0.0 |  | ClA | D |  |  |  |  | 1 |
| GDRX | 2026-06-10 | 4 |  | BEZDEK TREVOR |  | Y | N | N |  | N |  | 543377 | 0 | 543377 |  |  | ClA | I | TB 2024-2 GRAT |  |  |  | 2 |
| GDRX | 2026-06-10 | 4 |  | BEZDEK TREVOR |  | Y | N | N |  | N |  | 2089343 | 0 | 2089343 |  |  | ClA | I | TB 2025 GRAT |  |  |  | 3 |

### Last 5 Rows

_Skipped in fast mode or not inexpensive for this table._

### Date Coverage

**filingdate**
- `min_date`: 2025-08-01
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**transactiondate**
- `min_date`: 2006-06-12
- `max_date`: 2026-08-13
- `parsed_rows`: 75541
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**dateexercisable**
- `min_date`: 1988-08-08
- `max_date`: 2041-01-01
- `parsed_rows`: 6295
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**expirationdate**
- `min_date`: 1988-08-08
- `max_date`: 2050-12-31
- `parsed_rows`: 12908
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 4124
- `scope`: sample_first_100000_rows

### Categorical Values

**transactioncode**
| value | row_count |
| --- | --- |
|  | 25311 |
| S | 19880 |
| A | 19387 |
| M | 16314 |
| F | 9375 |
| P | 3480 |
| D | 2005 |
| G | 1344 |
| J | 1338 |
| C | 1278 |

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 31313 | 13350 | ['ticker', 'filingdate', 'transactiondate', 'ownername', 'transactioncode'] | sample_first_100000_rows |

### Table-Specific Checks

**ticker_identifier_fields**
- `ticker`
**transaction_date_fields**
- `transactiondate`
**transaction_type_fields**
- `formtype`
- `ownername`
- `istenpercentowner`
- `transactiondate`
- `securityadcode`
- `transactioncode`
- `sharesownedbeforetransaction`
- `transactionshares`
- `sharesownedfollowingtransaction`
- `transactionpricepershare`
- `transactionvalue`
- `natureofownership`
**primary_key_candidates**
- `['ticker', 'filingdate', 'transactiondate', 'ownername', 'transactioncode']`
**date_fields**
**filingdate**
- `min_date`: 2025-10-03
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**transactiondate**
- `min_date`: 2006-06-12
- `max_date`: 2026-08-13
- `parsed_rows`: 74835
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**dateexercisable**
- `min_date`: 1988-08-08
- `max_date`: 2032-07-31
- `parsed_rows`: 5734
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**expirationdate**
- `min_date`: 1988-08-08
- `max_date`: 2050-12-31
- `parsed_rows`: 12914
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**duplicate_key_behavior**
| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 31180 | 13451 | ['ticker', 'filingdate', 'transactiondate', 'ownername', 'transactioncode'] | sample_first_100000_rows |
**formtype_values**
| value | row_count |
| --- | --- |
| 4 | 93273 |
| 3 | 4745 |
| RESTATED - 4 | 1135 |
| 5 | 698 |
| RESTATED - 3 | 138 |
| RESTATED - 5 | 11 |
**securityadcode_values**
| value | row_count |
| --- | --- |
| ND | 31024 |
| NA | 23728 |
| N | 16716 |
| DD | 10584 |
| DA | 9230 |
| D | 8718 |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SF2_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.011 |
| duckdb_view_and_schema | 0.184 |
| example_rows | 0.102 |
| row_count | 0.003 |
| null_profile | 0.209 |
| date_ranges | 0.409 |
| distincts_and_categories | 0.205 |
| duplicate_key_checks | 0.105 |
| table_specific_checks | 0.721 |
| sample_csv | 0.099 |

## SF3A

File: `SHARADAR_SF3A_3_3cf8ee6560c114efbf672caf0a61b46c.csv`
Size: `90229067` bytes (`86.05 MB`)
Rows: `667,772`
Columns: `29`
Elapsed: `2.80s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| date | DATE | 0 | 0.0 | exact_full_table |
| ticker | VARCHAR | 0 | 0.0 | exact_full_table |
| name | VARCHAR | 0 | 0.0 | exact_full_table |
| shrholders | BIGINT | 0 | 0.0 | exact_full_table |
| cllholders | BIGINT | 0 | 0.0 | exact_full_table |
| putholders | BIGINT | 0 | 0.0 | exact_full_table |
| wntholders | BIGINT | 0 | 0.0 | exact_full_table |
| dbtholders | BIGINT | 0 | 0.0 | exact_full_table |
| prfholders | BIGINT | 0 | 0.0 | exact_full_table |
| fndholders | BIGINT | 0 | 0.0 | exact_full_table |
| undholders | BIGINT | 0 | 0.0 | exact_full_table |
| shrunits | DOUBLE | 0 | 0.0 | exact_full_table |
| cllunits | DOUBLE | 0 | 0.0 | exact_full_table |
| putunits | DOUBLE | 0 | 0.0 | exact_full_table |
| wntunits | DOUBLE | 0 | 0.0 | exact_full_table |
| dbtunits | DOUBLE | 0 | 0.0 | exact_full_table |
| prfunits | DOUBLE | 0 | 0.0 | exact_full_table |
| fndunits | DOUBLE | 0 | 0.0 | exact_full_table |
| undunits | DOUBLE | 0 | 0.0 | exact_full_table |
| shrvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| cllvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| putvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| wntvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| dbtvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| prfvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| fndvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| undvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| totalvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| percentoftotal | DOUBLE | 0 | 0.0 | exact_full_table |

### First 5 Rows

| date | ticker | name | shrholders | cllholders | putholders | wntholders | dbtholders | prfholders | fndholders | undholders | shrunits | cllunits | putunits | wntunits | dbtunits | prfunits | fndunits | undunits | shrvalue | cllvalue | putvalue | wntvalue | dbtvalue | prfvalue | fndvalue | undvalue | totalvalue | percentoftotal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2018-03-31 | VMVIX | VANGUARD MID-CAP VAL IDX FD | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 40.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.7 | 0.0 | 1.7 | 0.0 |
| 2018-03-31 | YTENQ | YIELD10 BIO INC | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 894.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.7 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.7 | 0.0 |
| 2018-03-31 | ACSI | AMERICAN CUSTOMER SATISFACTION ETF | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 52.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.6 | 0.0 | 1.6 | 0.0 |
| 2018-03-31 | ADYX | ADYNXX INC | 15 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 826.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.6 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.6 | 0.0 |
| 2018-03-31 | ALT | ALTIMMUNE INC | 28 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1352.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.6 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.6 | 0.0 |

### Last 5 Rows

| date | ticker | name | shrholders | cllholders | putholders | wntholders | dbtholders | prfholders | fndholders | undholders | shrunits | cllunits | putunits | wntunits | dbtunits | prfunits | fndunits | undunits | shrvalue | cllvalue | putvalue | wntvalue | dbtvalue | prfvalue | fndvalue | undvalue | totalvalue | percentoftotal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2018-06-30 | MTW | MANITOWOC CO INC | 163 | 11 | 10 | 0 | 0 | 0 | 0 | 0 | 29185.0 | 176.0 | 132.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 754.7 | 4.6 | 3.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 762.7 | 0.003 |
| 2018-06-30 | IYH | ISHARES U S HLTH ETF | 0 | 2 | 2 | 0 | 0 | 0 | 243 | 0 | 0.0 | 34.0 | 8.0 | 0.0 | 0.0 | 0.0 | 4475.0 | 0.0 | 0.0 | 6.1 | 1.4 | 0.0 | 0.0 | 0.0 | 754.8 | 0.0 | 762.3 | 0.003 |
| 2018-06-30 | NTRA | NATERA INC | 112 | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 40418.0 | 38.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 760.7 | 0.7 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 761.4 | 0.003 |
| 2018-06-30 | ASNAQ | MAHWAH BERGEN RETAIL GRP INC | 175 | 11 | 15 | 0 | 0 | 0 | 0 | 0 | 187075.0 | 1234.0 | 2346.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 745.5 | 4.9 | 9.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 759.7 | 0.003 |
| 2018-06-30 | FRPT | FRESHPET INC | 124 | 7 | 2 | 0 | 0 | 0 | 0 | 0 | 26488.0 | 1121.0 | 18.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 727.1 | 30.8 | 0.5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 758.4 | 0.003 |

### Date Coverage

**date**
- `min_date`: 2013-06-30
- `max_date`: 2026-06-30
- `parsed_rows`: 667772
- `profiled_rows`: 667772
- `scope`: exact_full_table

### Identifier Distinct Counts

**date**
- `column`: date
- `distinct_count`: 53
- `scope`: exact_full_table
**ticker**
- `column`: ticker
- `distinct_count`: 30971
- `scope`: exact_full_table

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | exact_full_table |

### Table-Specific Checks

**investor_identifier_fields**
_None._
**ticker_identifier_fields**
- `ticker`
**filing_calendar_date_fields**
- `date`
**quarter_fields**
_None._
**primary_key_candidates**
- `['ticker', 'date']`
**date_fields**
**date**
- `min_date`: 2013-06-30
- `max_date`: 2026-06-30
- `parsed_rows`: 667772
- `profiled_rows`: 667772
- `scope`: exact_full_table
**duplicate_key_behavior**
| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | exact_full_table |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SF3A_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.014 |
| duckdb_view_and_schema | 0.245 |
| example_rows | 0.561 |
| row_count | 0.193 |
| null_profile | 0.436 |
| date_ranges | 0.199 |
| distincts_and_categories | 0.402 |
| duplicate_key_checks | 0.215 |
| table_specific_checks | 0.41 |
| sample_csv | 0.128 |

## SF3B

File: `SHARADAR_SF3B_3_446434cb1641c8e62f602f9da186c53d.csv`
Size: `44980034` bytes (`42.90 MB`)
Rows: `303,139`
Columns: `29`
Elapsed: `2.64s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| date | DATE | 0 | 0.0 | exact_full_table |
| investorid | VARCHAR | 0 | 0.0 | exact_full_table |
| investorname | VARCHAR | 0 | 0.0 | exact_full_table |
| shrholdings | BIGINT | 0 | 0.0 | exact_full_table |
| cllholdings | BIGINT | 0 | 0.0 | exact_full_table |
| putholdings | BIGINT | 0 | 0.0 | exact_full_table |
| wntholdings | BIGINT | 0 | 0.0 | exact_full_table |
| dbtholdings | BIGINT | 0 | 0.0 | exact_full_table |
| prfholdings | BIGINT | 0 | 0.0 | exact_full_table |
| fndholdings | BIGINT | 0 | 0.0 | exact_full_table |
| undholdings | BIGINT | 0 | 0.0 | exact_full_table |
| shrunits | DOUBLE | 0 | 0.0 | exact_full_table |
| cllunits | DOUBLE | 0 | 0.0 | exact_full_table |
| putunits | DOUBLE | 0 | 0.0 | exact_full_table |
| wntunits | DOUBLE | 0 | 0.0 | exact_full_table |
| dbtunits | DOUBLE | 0 | 0.0 | exact_full_table |
| prfunits | DOUBLE | 0 | 0.0 | exact_full_table |
| fndunits | DOUBLE | 0 | 0.0 | exact_full_table |
| undunits | DOUBLE | 0 | 0.0 | exact_full_table |
| shrvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| cllvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| putvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| wntvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| dbtvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| prfvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| fndvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| undvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| totalvalue | DOUBLE | 0 | 0.0 | exact_full_table |
| percentoftotal | DOUBLE | 0 | 0.0 | exact_full_table |

### First 5 Rows

| date | investorid | investorname | shrholdings | cllholdings | putholdings | wntholdings | dbtholdings | prfholdings | fndholdings | undholdings | shrunits | cllunits | putunits | wntunits | dbtunits | prfunits | fndunits | undunits | shrvalue | cllvalue | putvalue | wntvalue | dbtvalue | prfvalue | fndvalue | undvalue | totalvalue | percentoftotal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2013-12-31 | BAINC2 | BAIN CAPITAL PUBLIC EQUITY MANAGEMENT LLC | 43 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 98539.0 | 0.0 | 0.0 | 14078.0 | 0.0 | 721.0 | 0.0 | 0.0 | 3468.5 | 0.0 | 0.0 | 57.2 | 0.0 | 13.9 | 0.0 | 0.0 | 3539.6 | 0.017 |
| 2013-12-31 | DENVE1 | DENVER INVESTMENT ADVISORS LLC | 533 | 0 | 0 | 0 | 0 | 4 | 37 | 1 | 78150.0 | 0.0 | 0.0 | 0.0 | 0.0 | 288.0 | 846.0 | 640.0 | 3460.9 | 0.0 | 0.0 | 0.0 | 0.0 | 4.5 | 52.9 | 20.6 | 3538.9 | 0.017 |
| 2013-12-31 | BAUPOS | BAUPOST GROUP LLC | 17 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 183374.0 | 0.0 | 0.0 | 104902.0 | 0.0 | 0.0 | 0.0 | 0.0 | 3448.3 | 0.0 | 0.0 | 81.1 | 0.0 | 0.0 | 0.0 | 0.0 | 3529.4 | 0.017 |
| 2013-12-31 | FLOVSS | FLOSSBACH VON STORCH SE | 76 | 2 | 0 | 0 | 8 | 0 | 1 | 0 | 73378.0 | 4.0 | 0.0 | 0.0 | 44500.0 | 0.0 | 30.0 | 0.0 | 3450.7 | 13.3 | 0.0 | 0.0 | 47.1 | 0.0 | 3.5 | 0.0 | 3514.6 | 0.017 |
| 2013-12-31 | MHRFUN | MHR FUND MANAGEMENT LLC | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 120543.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 3510.8 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 3510.8 | 0.017 |

### Last 5 Rows

| date | investorid | investorname | shrholdings | cllholdings | putholdings | wntholdings | dbtholdings | prfholdings | fndholdings | undholdings | shrunits | cllunits | putunits | wntunits | dbtunits | prfunits | fndunits | undunits | shrvalue | cllvalue | putvalue | wntvalue | dbtvalue | prfvalue | fndvalue | undvalue | totalvalue | percentoftotal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-03-31 | SAGEVI | SAGEVIEW ADVISORY GROUP LLC | 306 | 0 | 0 | 0 | 0 | 0 | 213 | 0 | 4413.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 25458.0 | 0.0 | 416.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1563.9 | 0.0 | 1980.2 | 0.004 |
| 2024-03-31 | THELEM | THELEME PARTNERS LLP | 7 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 21848.0 | 1440.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1820.0 | 153.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1973.4 | 0.004 |
| 2024-03-31 | NICHOF | NICHOLAS HOFFMAN COMPANY LLC | 209 | 0 | 0 | 0 | 0 | 0 | 80 | 0 | 4411.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 14911.0 | 0.0 | 485.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1485.1 | 0.0 | 1971.0 | 0.004 |
| 2024-03-31 | INTNET | INTEGRATED ADVISORS NETWORK LLC | 396 | 9 | 3 | 1 | 2 | 0 | 290 | 0 | 11186.0 | 134.0 | 8.0 | 462.0 | 93.0 | 0.0 | 12219.0 | 0.0 | 971.6 | 7.9 | 5.3 | 0.8 | 0.1 | 0.0 | 983.6 | 0.0 | 1969.3 | 0.004 |
| 2024-03-31 | AMIASS | AMI ASSET MANAGEMENT CORP | 79 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 12719.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 12.0 | 0.0 | 1952.4 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 4.0 | 0.0 | 1956.4 | 0.004 |

### Date Coverage

**date**
- `min_date`: 2013-06-30
- `max_date`: 2026-06-30
- `parsed_rows`: 303139
- `profiled_rows`: 303139
- `scope`: exact_full_table

### Identifier Distinct Counts

**date**
- `column`: date
- `distinct_count`: 53
- `scope`: exact_full_table
**investorid**
- `column`: investorid
- `distinct_count`: 13184
- `scope`: exact_full_table

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['investorid', 'date'] | exact_full_table |

### Table-Specific Checks

**investor_identifier_fields**
- `investorid`
- `investorname`
**ticker_identifier_fields**
_None._
**filing_calendar_date_fields**
- `date`
**quarter_fields**
_None._
**primary_key_candidates**
- `['investorid', 'date']`
**date_fields**
**date**
- `min_date`: 2013-06-30
- `max_date`: 2026-06-30
- `parsed_rows`: 303139
- `profiled_rows`: 303139
- `scope`: exact_full_table
**unique_investor_count**
- `column`: investorid
- `distinct_count`: 13184
- `scope`: exact_full_table
**duplicate_key_behavior**
| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['investorid', 'date'] | exact_full_table |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SF3B_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.017 |
| duckdb_view_and_schema | 0.271 |
| example_rows | 0.486 |
| row_count | 0.166 |
| null_profile | 0.36 |
| date_ranges | 0.17 |
| distincts_and_categories | 0.355 |
| duplicate_key_checks | 0.176 |
| table_specific_checks | 0.502 |
| sample_csv | 0.134 |

## SF3

File: `SHARADAR_SF3_3_f56744e079d18324f1cc8ed6e63569a1.csv`
Size: `2847414157` bytes (`2.65 GB`)
Rows: `~79,809,754`
Columns: `6`
Elapsed: `0.68s`

### Issues And Warnings

- Warning: Row count is estimated in default mode; run with --full-profile for exact DuckDB count.
- Warning: Null counts and percentages are sample-based in default mode for large tables.
- Warning: Duplicate key checks are sample-based in default mode for this table.

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| investorid | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| securitytype | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| date | DATE | 0 | 0.0 | sample_first_100000_rows |
| value | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| units | DOUBLE | 0 | 0.0 | sample_first_100000_rows |

### First 5 Rows

| ticker | investorid | securitytype | date | value | units |
| --- | --- | --- | --- | --- | --- |
| MRK | CORNE3 | SHR | 2023-06-30 | 4.2 | 37.0 |
| MRK | CRENAS | SHR | 2023-06-30 | 4.2 | 36.0 |
| MRK | DFDENT | SHR | 2023-06-30 | 4.2 | 36.0 |
| MRK | GLOBAL | SHR | 2023-06-30 | 4.2 | 36.0 |
| MRK | HEROLD | SHR | 2023-06-30 | 4.2 | 36.0 |

### Last 5 Rows

_Skipped in fast mode or not inexpensive for this table._

### Date Coverage

**date**
- `min_date`: 2023-06-30
- `max_date`: 2025-06-30
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 6798
- `scope`: sample_first_100000_rows
**investorid**
- `column`: investorid
- `distinct_count`: 6874
- `scope`: sample_first_100000_rows
**date**
- `column`: date
- `distinct_count`: 2
- `scope`: sample_first_100000_rows

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 998 | 754 | ['ticker', 'investorid', 'date'] | sample_first_100000_rows |

### Table-Specific Checks

**investor_identifier_fields**
- `investorid`
**ticker_identifier_fields**
- `ticker`
**filing_calendar_date_fields**
- `date`
**quarter_fields**
_None._
**primary_key_candidates**
- `['ticker', 'investorid', 'date']`
**date_fields**
**date**
- `min_date`: 2023-06-30
- `max_date`: 2025-06-30
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**unique_investor_count**
- `column`: investorid
- `distinct_count`: 6854
- `scope`: sample_first_100000_rows
**duplicate_key_behavior**
| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 807 | 654 | ['ticker', 'investorid', 'date'] | sample_first_100000_rows |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SF3_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.005 |
| duckdb_view_and_schema | 0.087 |
| example_rows | 0.06 |
| row_count | 0.003 |
| null_profile | 0.096 |
| date_ranges | 0.047 |
| distincts_and_categories | 0.147 |
| duplicate_key_checks | 0.05 |
| table_specific_checks | 0.142 |
| sample_csv | 0.048 |

## SFP

File: `SHARADAR_SFP_2_4f56514c067b4bbae40297a156380a56.csv`
Size: `1101731059` bytes (`1.03 GB`)
Rows: `~15,551,586`
Columns: `10`
Elapsed: `2.16s`

### Issues And Warnings

- Warning: Row count is estimated in default mode; run with --full-profile for exact DuckDB count.
- Warning: Null counts and percentages are sample-based in default mode for large tables.
- Warning: Duplicate key checks are sample-based in default mode for this table.

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| ticker | VARCHAR | 0 | 0.0 | sample_first_100000_rows |
| date | DATE | 0 | 0.0 | sample_first_100000_rows |
| open | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| high | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| low | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| close | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| volume | DOUBLE | 18 | 0.018 | sample_first_100000_rows |
| closeadj | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| closeunadj | DOUBLE | 0 | 0.0 | sample_first_100000_rows |
| lastupdated | DATE | 0 | 0.0 | sample_first_100000_rows |

### First 5 Rows

| ticker | date | open | high | low | close | volume | closeadj | closeunadj | lastupdated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KNOW1 | 2018-02-12 | 40.1 | 40.449 | 39.827 | 40.2 | 34971.0 | 37.939 | 40.2 | 2024-02-22 |
| KNOW1 | 2018-02-09 | 39.77 | 39.93 | 38.62 | 39.8 | 50957.0 | 37.561 | 39.8 | 2024-02-22 |
| BBCB | 2024-12-05 | 45.94 | 45.988 | 45.891 | 45.967 | 4600.0 | 42.439 | 45.967 | 2026-08-03 |
| BBCB | 2024-12-04 | 45.745 | 46.03 | 45.71 | 45.95 | 2800.0 | 42.423 | 45.95 | 2026-08-03 |
| EOCT | 2023-12-15 | 23.39 | 23.39 | 23.285 | 23.285 | 29676.0 | 23.285 | 23.285 | 2023-12-15 |

### Last 5 Rows

_Skipped in fast mode or not inexpensive for this table._

### Date Coverage

**date**
- `min_date`: 1997-12-31
- `max_date`: 2026-08-03
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**lastupdated**
- `min_date`: 2020-12-23
- `max_date`: 2026-08-13
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows

### Identifier Distinct Counts

**ticker**
- `column`: ticker
- `distinct_count`: 5109
- `scope`: sample_first_100000_rows
**date**
- `column`: date
- `distinct_count`: 7053
- `scope`: sample_first_100000_rows

### Categorical Values

_None._

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date'] | sample_first_100000_rows |

### Table-Specific Checks

**price_columns_available**
- `open`
- `high`
- `low`
- `close`
- `volume`
- `closeadj`
- `closeunadj`
- `lastupdated`
**unique_tickers**
- `column`: ticker
- `distinct_count`: 5199
- `scope`: sample_first_100000_rows
**date_range**
- `min_date`: 1997-12-31
- `max_date`: 2026-08-03
- `parsed_rows`: 100000
- `profiled_rows`: 100000
- `scope`: sample_first_100000_rows
**duplicate_ticker_date**
- `duplicate_rows`: 0
- `duplicate_keys`: 0
**key**
- `ticker`
- `date`
- `scope`: sample_first_100000_rows
**major_etf_sample_rows**
| ticker | date | open | high | low | close | volume | closeadj | closeunadj | lastupdated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IWM | 2026-08-13 | 304.04 | 305.05 | 302.72 | 303.5 | 13990000.0 | 303.5 | 303.5 | 2026-08-13 |
| IWM | 2026-08-12 | 303.02 | 303.4 | 301.0 | 302.71 | 15404000.0 | 302.71 | 302.71 | 2026-08-12 |
| IWM | 2026-08-11 | 300.93 | 301.99 | 300.6 | 300.99 | 14696000.0 | 300.99 | 300.99 | 2026-08-11 |
| IWM | 2026-08-10 | 300.51 | 301.39 | 299.09 | 299.98 | 16032000.0 | 299.98 | 299.98 | 2026-08-10 |
| IWM | 2026-08-07 | 300.46 | 302.03 | 299.8 | 301.56 | 18400000.0 | 301.56 | 301.56 | 2026-08-09 |
| IWM | 2026-08-06 | 299.6 | 301.375 | 297.96 | 298.25 | 16143000.0 | 298.25 | 298.25 | 2026-08-06 |
| IWM | 2026-08-05 | 302.43 | 303.06 | 299.755 | 299.77 | 17688000.0 | 299.77 | 299.77 | 2026-08-05 |
| IWM | 2026-08-04 | 297.59 | 302.39 | 297.22 | 301.71 | 20365000.0 | 301.71 | 301.71 | 2026-08-04 |
| IWM | 2026-08-03 | 292.9 | 296.66 | 292.4 | 296.22 | 21670000.0 | 296.22 | 296.22 | 2026-08-03 |
| IWM | 2026-07-31 | 293.56 | 293.93 | 287.83 | 291.2 | 28022000.0 | 291.2 | 291.2 | 2026-08-01 |
| IWM | 2026-07-30 | 291.15 | 292.84 | 288.96 | 292.59 | 21999000.0 | 292.59 | 292.59 | 2026-07-30 |
| IWM | 2026-07-29 | 292.49 | 293.66 | 288.26 | 288.57 | 32839000.0 | 288.57 | 288.57 | 2026-07-29 |
| IWM | 2026-07-28 | 293.16 | 293.77 | 290.375 | 293.37 | 19696000.0 | 293.37 | 293.37 | 2026-07-28 |
| IWM | 2026-07-27 | 293.98 | 295.51 | 291.11 | 292.91 | 18970000.0 | 292.91 | 292.91 | 2026-07-27 |
| IWM | 2026-07-24 | 293.41 | 293.97 | 290.48 | 291.17 | 19763000.0 | 291.17 | 291.17 | 2026-07-31 |
| IWM | 2026-07-23 | 290.87 | 293.01 | 290.17 | 292.09 | 27795000.0 | 292.09 | 292.09 | 2026-07-31 |
| IWM | 2026-07-22 | 295.7 | 296.43 | 293.41 | 293.79 | 19116000.0 | 293.79 | 293.79 | 2026-07-31 |
| IWM | 2026-07-21 | 293.43 | 296.75 | 292.69 | 296.54 | 18190000.0 | 296.54 | 296.54 | 2026-07-31 |
| IWM | 2026-07-20 | 295.01 | 295.99 | 292.18 | 292.31 | 20540000.0 | 292.31 | 292.31 | 2026-07-31 |
| IWM | 2026-07-17 | 292.03 | 296.13 | 291.65 | 294.04 | 28354000.0 | 294.04 | 294.04 | 2026-07-18 |

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SFP_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.007 |
| duckdb_view_and_schema | 0.126 |
| example_rows | 0.073 |
| row_count | 0.003 |
| null_profile | 0.145 |
| date_ranges | 0.14 |
| distincts_and_categories | 0.137 |
| duplicate_key_checks | 0.071 |
| table_specific_checks | 1.39 |
| sample_csv | 0.068 |

## SP500

File: `SHARADAR_SP500_2_a5d269df7633595315f85e40f3491992.csv`
Size: `3288742` bytes (`3.14 MB`)
Rows: `59,672`
Columns: `7`
Elapsed: `1.14s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| date | DATE | 0 | 0.0 | exact_full_table |
| action | VARCHAR | 0 | 0.0 | exact_full_table |
| ticker | VARCHAR | 0 | 0.0 | exact_full_table |
| name | VARCHAR | 0 | 0.0 | exact_full_table |
| contraticker | VARCHAR | 0 | 0.0 | exact_full_table |
| contraname | VARCHAR | 0 | 0.0 | exact_full_table |
| note | VARCHAR | 58071 | 97.317 | exact_full_table |

### First 5 Rows

| date | action | ticker | name | contraticker | contraname | note |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-08-13 | current | A | AGILENT TECHNOLOGIES INC | N/A | N/A |  |
| 2026-08-13 | current | AAPL | APPLE INC | N/A | N/A |  |
| 2026-08-13 | current | ABBV | ABBVIE INC | N/A | N/A |  |
| 2026-08-13 | current | ABNB | AIRBNB INC | N/A | N/A |  |
| 2026-08-13 | current | ABT | ABBOTT LABORATORIES | N/A | N/A |  |

### Last 5 Rows

| date | action | ticker | name | contraticker | contraname | note |
| --- | --- | --- | --- | --- | --- | --- |
| 1957-03-04 | added | VO1 | SEAGRAM CO LTD | N/A | N/A | Original S&P 500 constituent (March 4 1957). |
| 1957-03-04 | added | WGL | WGL HOLDINGS INC | N/A | N/A | Original S&P 500 constituent (March 4 1957). |
| 1957-03-04 | added | WLA | WARNER LAMBERT CO | N/A | N/A | Original S&P 500 constituent (March 4 1957). |
| 1957-03-04 | added | WNDXQ | WINN DIXIE STORES INC | N/A | N/A | Original S&P 500 constituent (March 4 1957). |
| 1957-03-04 | added | WWY | WRIGLEY WM JR CO | N/A | N/A | Original S&P 500 constituent (March 4 1957). |

### Date Coverage

**date**
- `min_date`: 1957-03-04
- `max_date`: 2026-08-13
- `parsed_rows`: 59672
- `profiled_rows`: 59672
- `scope`: exact_full_table

### Identifier Distinct Counts

**date**
- `column`: date
- `distinct_count`: 965
- `scope`: exact_full_table
**ticker**
- `column`: ticker
- `distinct_count`: 1203
- `scope`: exact_full_table

### Categorical Values

**action**
| value | row_count |
| --- | --- |
| historical | 57194 |
| added | 1236 |
| removed | 739 |
| current | 503 |

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date', 'action'] | exact_full_table |
| 29 | 29 | ['ticker', 'date'] | exact_full_table |

### Table-Specific Checks

**columns**
- `date`
- `action`
- `ticker`
- `name`
- `contraticker`
- `contraname`
- `note`
**unique_tickers**
- `column`: ticker
- `distinct_count`: 1203
- `scope`: exact_full_table
**action_values**
| value | row_count |
| --- | --- |
| historical | 57194 |
| added | 1236 |
| removed | 739 |
| current | 503 |
**action_addition_examples**
| date | action | ticker | name | contraticker | contraname | note |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-08-13 | current | A | AGILENT TECHNOLOGIES INC | N/A | N/A |  |
| 2026-08-13 | current | AAPL | APPLE INC | N/A | N/A |  |
| 2026-08-13 | current | ABBV | ABBVIE INC | N/A | N/A |  |
| 2026-08-13 | current | ABNB | AIRBNB INC | N/A | N/A |  |
| 2026-08-13 | current | ABT | ABBOTT LABORATORIES | N/A | N/A |  |
**action_deletion_examples**
| date | action | ticker | name | contraticker | contraname | note |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-08-05 | removed | EA | ELECTRONIC ARTS INC | FERG | FERGUSON ENTERPRISES INC | Electronic Arts Inc was acquired by Public Investment Fund and Silver Lake Pa... |
| 2026-06-30 | removed | CAG | CONAGRA BRANDS INC | HONA | HONEYWELL AEROSPACE INC | S&P 500 constituent Honeywell completed the corporate spin-off of Honeywell A... |
| 2026-06-22 | removed | CPB | CAMPBELL'S CO | FLEX | FLEX LTD | Market capitalization change. |
| 2026-06-22 | removed | POOL | POOL CORP | MRVL | MARVELL TECHNOLOGY INC | Market capitalization change. |
| 2026-06-02 | removed | EPAM | EPAM SYSTEMS INC | FDXF | FEDEX FREIGHT HOLDING COMPANY INC | FedEx Corp. completed the corporate spin-off of FedEx Freight Holding. |
**date_fields**
**date**
- `min_date`: 1957-03-04
- `max_date`: 2026-08-13
- `parsed_rows`: 59672
- `profiled_rows`: 59672
- `scope`: exact_full_table
**duplicate_behavior**
| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 0 | 0 | ['ticker', 'date', 'action'] | exact_full_table |
| 29 | 29 | ['ticker', 'date'] | exact_full_table |
- `likely_historical_membership_logic`: Schema has an action-like field and date-like field(s); reconstructing membership likely requires replaying local add...

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/SP500_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.006 |
| duckdb_view_and_schema | 0.087 |
| example_rows | 0.147 |
| row_count | 0.05 |
| null_profile | 0.107 |
| date_ranges | 0.053 |
| distincts_and_categories | 0.158 |
| duplicate_key_checks | 0.114 |
| table_specific_checks | 0.375 |
| sample_csv | 0.042 |

## TICKERS

File: `SHARADAR_TICKERS_3_9d55c66cf84cd02091405a84d061ba83.csv`
Size: `20454347` bytes (`19.51 MB`)
Rows: `62,779`
Columns: `28`
Elapsed: `6.01s`

### Schema

| Column | Type | Null Count | Null % | Null Scope |
| --- | --- | --- | --- | --- |
| table | VARCHAR | 0 | 0.0 | exact_full_table |
| permaticker | BIGINT | 0 | 0.0 | exact_full_table |
| ticker | VARCHAR | 0 | 0.0 | exact_full_table |
| name | VARCHAR | 0 | 0.0 | exact_full_table |
| exchange | VARCHAR | 13209 | 21.0405 | exact_full_table |
| isdelisted | VARCHAR | 13209 | 21.0405 | exact_full_table |
| category | VARCHAR | 0 | 0.0 | exact_full_table |
| cusips | VARCHAR | 13351 | 21.2667 | exact_full_table |
| siccode | BIGINT | 22226 | 35.4036 | exact_full_table |
| sicsector | VARCHAR | 22226 | 35.4036 | exact_full_table |
| sicindustry | VARCHAR | 22226 | 35.4036 | exact_full_table |
| figi | VARCHAR | 36259 | 57.7566 | exact_full_table |
| famaindustry | VARCHAR | 22980 | 36.6046 | exact_full_table |
| sector | VARCHAR | 22844 | 36.388 | exact_full_table |
| industry | VARCHAR | 22844 | 36.388 | exact_full_table |
| scalemarketcap | VARCHAR | 27340 | 43.5496 | exact_full_table |
| scalerevenue | VARCHAR | 29775 | 47.4283 | exact_full_table |
| relatedtickers | VARCHAR | 39541 | 62.9844 | exact_full_table |
| currency | VARCHAR | 0 | 0.0 | exact_full_table |
| location | VARCHAR | 8459 | 13.4743 | exact_full_table |
| lastupdated | DATE | 13209 | 21.0405 | exact_full_table |
| firstadded | DATE | 13209 | 21.0405 | exact_full_table |
| firstpricedate | DATE | 13209 | 21.0405 | exact_full_table |
| lastpricedate | DATE | 13209 | 21.0405 | exact_full_table |
| firstquarter | DATE | 13957 | 22.232 | exact_full_table |
| lastquarter | DATE | 13957 | 22.232 | exact_full_table |
| secfilings | VARCHAR | 604 | 0.9621 | exact_full_table |
| companysite | VARCHAR | 51260 | 81.6515 | exact_full_table |

### First 5 Rows

| table | permaticker | ticker | name | exchange | isdelisted | category | cusips | siccode | sicsector | sicindustry | figi | famaindustry | sector | industry | scalemarketcap | scalerevenue | relatedtickers | currency | location | lastupdated | firstadded | firstpricedate | lastpricedate | firstquarter | lastquarter | secfilings | companysite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SFP | 118871 | DMO | WESTERN ASSET MORTGAGE OPPORTUNITY FUND INC | NYSE | N | CEF | 95790B109 |  |  |  | BBG000M77RS2 |  |  |  |  |  |  | USD | New York; U.S.A | 2026-08-13 | 2018-06-07 | 2010-02-24 | 2026-08-13 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001478102 | http://individualinvestor.myleggmason.com/portal/server.pt?open=512&objID=143... |
| SFP | 111089 | DMRE | DELTASHARES S&P EM 100 & MANAGED RISK ETF | NYSEARCA | Y | ETF | 89349P503 |  |  |  |  |  |  |  |  |  |  | USD | Colorado; U.S.A | 2022-04-07 | 2019-03-21 | 2019-03-21 | 2022-04-07 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001673996 |  |
| SFP | 117196 | DMRI | DELTASHARES S&P INTERNATIONAL MANAGED RISK ETF | NYSEARCA | Y | ETF | 89349P404 |  |  |  |  |  |  |  |  |  |  | USD | Colorado; U.S.A | 2022-04-07 | 2018-06-07 | 2017-08-02 | 2022-04-07 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001673996 |  |
| SFP | 117199 | DMRL | DELTASHARES S&P 500 MANAGED RISK ETF | NYSEARCA | Y | ETF | 89349P107 |  |  |  |  |  |  |  |  |  |  | USD | Colorado; U.S.A | 2022-04-07 | 2018-06-07 | 2017-08-02 | 2022-04-07 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001673996 |  |
| SFP | 117198 | DMRM | DELTASHARES S&P 400 MANAGED RISK ETF | NYSEARCA | Y | ETF | 89349P206 |  |  |  |  |  |  |  |  |  |  | USD | Colorado; U.S.A | 2022-04-07 | 2018-06-07 | 2017-08-02 | 2022-04-07 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001673996 |  |

### Last 5 Rows

| table | permaticker | ticker | name | exchange | isdelisted | category | cusips | siccode | sicsector | sicindustry | figi | famaindustry | sector | industry | scalemarketcap | scalerevenue | relatedtickers | currency | location | lastupdated | firstadded | firstpricedate | lastpricedate | firstquarter | lastquarter | secfilings | companysite |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SFP | 639895 | DMBS | DOUBLELINE MORTGAGE ETF | NYSEARCA | N | ETF | 25861R402 |  |  |  | BBG01G091LD1 |  |  |  |  |  |  | USD | Florida; U.S.A | 2026-08-13 | 2023-04-04 | 2023-04-04 | 2026-08-13 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001886172 |  |
| SFP | 634648 | DMCY | DEMOCRACY INTERNATIONAL FUND | NYSEARCA | Y | ETF | 00774Q148 |  |  |  | BBG00ZVNNVW8 |  |  |  |  |  |  | USD | Pennsylvania; U.S.A | 2026-03-20 | 2021-04-01 | 2021-04-01 | 2026-02-17 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001593547 |  |
| SFP | 113319 | DMDV | AAM S&P DEVELOPED MARKETS HIGH DIVIDEND VALUE ETF | NYSEARCA | Y | ETF | 26922A347 |  |  |  | BBG00MNVY1S7 |  |  |  |  |  |  | USD | Wisconsin; U.S.A | 2024-10-17 | 2018-12-20 | 2018-11-28 | 2024-10-17 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001540305 |  |
| SFP | 118790 | DMF | BNY MELLON MUNICIPAL INCOME INC | NYSEMKT | Y | CEF | 05589T104 26201R102 |  |  |  | BBG000BTKJJ9 |  |  |  |  |  |  | USD | New York; U.S.A | 2025-06-17 | 2018-06-07 | 1991-11-25 | 2025-06-17 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000839122 |  |
| SFP | 111006 | DMM | MACROSHARES MAJOR METRO HOUSING DOWN TRUST | NYSE | Y | ETF | 55610X103 | 6189 | Finance Insurance And Real Estate | Asset-Backed Securities |  |  |  |  |  |  |  | USD | New Jersey; U.S.A | 2020-07-21 | 2019-04-11 | 2009-06-30 | 2009-12-28 |  |  | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001436205 |  |

### Date Coverage

**lastupdated**
- `min_date`: 2018-06-13
- `max_date`: 2026-08-13
- `parsed_rows`: 49570
- `profiled_rows`: 62779
- `scope`: exact_full_table
**firstpricedate**
- `min_date`: 1986-01-01
- `max_date`: 2026-08-11
- `parsed_rows`: 49570
- `profiled_rows`: 62779
- `scope`: exact_full_table
**lastpricedate**
- `min_date`: 1996-09-05
- `max_date`: 2026-08-13
- `parsed_rows`: 49570
- `profiled_rows`: 62779
- `scope`: exact_full_table
**firstquarter**
- `min_date`: 1990-06-30
- `max_date`: 2026-06-30
- `parsed_rows`: 48822
- `profiled_rows`: 62779
- `scope`: exact_full_table
**lastquarter**
- `min_date`: 1996-03-31
- `max_date`: 2026-06-30
- `parsed_rows`: 48822
- `profiled_rows`: 62779
- `scope`: exact_full_table

### Identifier Distinct Counts

**permaticker**
- `column`: permaticker
- `distinct_count`: 44737
- `scope`: exact_full_table
**ticker**
- `column`: ticker
- `distinct_count`: 31776
- `scope`: exact_full_table

### Categorical Values

**table**
| value | row_count |
| --- | --- |
| SEP | 21962 |
| SF1 | 17817 |
| SF3B | 13209 |
| SFP | 9791 |
**exchange**
| value | row_count |
| --- | --- |
| NASDAQ | 27337 |
| NYSE | 13540 |
|  | 13209 |
| NYSEARCA | 4064 |
| NYSEMKT | 2662 |
| BATS | 1954 |
| OTC | 8 |
| INDEX | 5 |
**isdelisted**
| value | row_count |
| --- | --- |
| Y | 31518 |
| N | 18052 |
|  | 13209 |
**category**
| value | row_count |
| --- | --- |
| Domestic Common Stock | 26965 |
| Institutional Investor | 13209 |
| ETF | 7632 |
| Domestic Common Stock Primary Class | 4350 |
| ADR Common Stock | 3467 |
| Domestic Common Stock Secondary Class | 1320 |
| Domestic Preferred Stock | 1137 |
| CEF | 1072 |
| Domestic Common Stock Warrant | 917 |
| Canadian Common Stock | 698 |
**sector**
| value | row_count |
| --- | --- |
|  | 22844 |
| Technology | 7231 |
| Industrials | 7015 |
| Healthcare | 6083 |
| Financial Services | 5776 |
| Consumer Cyclical | 3837 |
| Communication Services | 2116 |
| Basic Materials | 2026 |
| Energy | 1813 |
| Real Estate | 1731 |
**industry**
| value | row_count |
| --- | --- |
|  | 22844 |
| Software - Application | 3515 |
| Banks - Regional | 3124 |
| Shell Companies | 3065 |
| Biotechnology | 3061 |
| Medical Devices | 1124 |
| Telecom Services | 1034 |
| Oil & Gas E&P | 848 |
| Communication Equipment | 772 |
| REIT - Mortgage | 603 |

### Duplicate Key Checks

| duplicate_rows | duplicate_keys | key | scope |
| --- | --- | --- | --- |
| 31003 | 17796 | ['ticker'] | exact_full_table |
| 18042 | 17803 | ['permaticker'] | exact_full_table |

### Table-Specific Checks

**requested_fields_present**
- `ticker`
- `permaticker`
- `table`
- `exchange`
- `category`
- `sector`
- `industry`
- `firstpricedate`
- `lastpricedate`
- `firstquarter`
- `lastquarter`
- `isdelisted`
**related_ticker_fields**
- `permaticker`
- `ticker`
- `relatedtickers`
- `total_securities`: 62779
**table_counts**
| value | row_count |
| --- | --- |
| SEP | 21962 |
| SF1 | 17817 |
| SF3B | 13209 |
| SFP | 9791 |
- `sep_securities`: 21962
- `sfp_securities`: 9791
**delisted_counts**
| value | row_count |
| --- | --- |
| Y | 31518 |
| N | 18052 |
|  | 13209 |
- `delisted_securities`: 31518
**unique_tickers**
- `column`: ticker
- `distinct_count`: 31776
- `scope`: exact_full_table
**duplicate_tickers**
- `duplicate_rows`: 31003
- `duplicate_keys`: 17796
**key**
- `ticker`
- `scope`: exact_full_table
**unique_permatickers**
- `column`: permaticker
- `distinct_count`: 44737
- `scope`: exact_full_table
**duplicate_permatickers**
- `duplicate_rows`: 18042
- `duplicate_keys`: 17803
**key**
- `permaticker`
- `scope`: exact_full_table

### Sample CSV

`/Users/terenceobrien/AI_Financial_Operator/backend/data/sharadar/profile/sample_rows/TICKERS_sample.csv`

### Timing

| Step | Seconds |
| --- | --- |
| header_scan | 0.025 |
| duckdb_view_and_schema | 0.327 |
| example_rows | 0.528 |
| row_count | 0.175 |
| null_profile | 0.362 |
| date_ranges | 0.878 |
| distincts_and_categories | 1.413 |
| duplicate_key_checks | 0.375 |
| table_specific_checks | 1.758 |
| sample_csv | 0.165 |
