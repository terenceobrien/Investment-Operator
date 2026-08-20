# Sharadar TICKERS QA

Generated: `2026-08-15T01:04:23.997556+00:00`
Total rows: `62779`

## Table Counts
| table | rows |
| --- | --- |
| SEP | 21962 |
| SF1 | 17817 |
| SF3B | 13209 |
| SFP | 9791 |

## duplicate ticker values across all Sharadar tables
Duplicate keys: `17796`
| ticker | rows |
| --- | --- |
| N/A | 13209 |
| ADT1 | 2 |
| AAMCF | 2 |
| ADAC1 | 2 |
| ABIO1 | 2 |
| ACTI | 2 |
| ACVC | 2 |
| AERG | 2 |
| ADLR | 2 |
| ADMS | 2 |
| ADSK | 2 |
| ADSW | 2 |
| AAWW | 2 |
| ADZA | 2 |
| AEON | 2 |
| AIQ1 | 2 |
| AFIIQ | 2 |
| AFLX | 2 |
| AFRM | 2 |
| AFSC1 | 2 |
| AHE | 2 |
| AHPIQ | 2 |
| AIIA | 2 |
| AIMC | 2 |
| AACC | 2 |

## duplicate permaticker values across all Sharadar tables
Duplicate keys: `17803`
| permaticker | rows |
| --- | --- |
| 199867 | 3 |
| 199571 | 3 |
| 195843 | 3 |
| 199185 | 3 |
| 198830 | 3 |
| 121536 | 3 |
| 195425 | 3 |
| 196179 | 3 |
| 199495 | 3 |
| 198566 | 3 |
| 198535 | 3 |
| 195652 | 3 |
| 195694 | 3 |
| 114459 | 3 |
| 119344 | 3 |
| 191779 | 3 |
| 199840 | 3 |
| 199259 | 3 |
| 199306 | 3 |
| 196511 | 3 |
| 198807 | 3 |
| 121542 | 3 |
| 188223 | 3 |
| 192254 | 3 |
| 179780 | 3 |

## duplicate (table, ticker) combinations
Duplicate keys: `1`
| table | ticker | rows |
| --- | --- | --- |
| SF3B | N/A | 13209 |

## duplicate (table, permaticker) combinations
Duplicate keys: `0`
_None._

## Ticker To Multiple Permatickers
| table | ticker | distinct_permatickers | sample_min_permaticker | sample_max_permaticker | rows |
| --- | --- | --- | --- | --- | --- |
| SF3B | N/A | 13209 | 100044 | 6401071 | 13209 |

## Permaticker To Multiple Tickers
_None._

Ticker and permaticker are diagnostics only here; no historical SP500 membership tickers are rewritten.
