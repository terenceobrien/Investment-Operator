# S&P 500 Historical Breadth QA

Generated: `2026-08-15T18:00:45.366953+00:00`
Rows: `7137`
Period: `1998-03-31` -> `2026-08-13`

## First Valid Dates
- `first_membership_date`: 1998-03-31
- `first_price_coverage_ge_95`: 1998-03-31
- `first_ma20_breadth_sufficient`: 1998-03-31
- `first_ma50_breadth_sufficient`: 1998-03-31
- `first_ma100_breadth_sufficient`: 1998-05-26
- `first_ma200_breadth_sufficient`: 1998-10-15
- `first_252d_breadth_sufficient`: 1998-12-30
- `first_adl_date`: 1998-03-31
- `first_normalized_signal_date`: 1999-04-15

## Range Checks
- `pct_fields_0_100`: pass
- `pct_positive_0_100`: pass
- `ad_balance_minus1_plus1`: pass
- `forward_maxdd_le_0`: pass

## Lookback And Research-Safety Checks
- `moving_averages_require_full_lookback`: pass
- `missing_ma_not_in_denominator`: pass
- `point_in_time_membership_used_each_date`: pass
- `pre_membership_prices_used_only_for_technical_lookbacks`: pass
- `no_future_prices_enter_technical_features`: pass
- `normalized_percentiles_use_prior_history_only`: pass
- `forward_outcomes_isolated`: pass
- `forward_return_paths_aligned_to_date_t`: pass
- `duplicate_daily_rows`: 0

## Low Coverage Dates
_None._

## Unusual Member Counts
_None._

## Manual Recomputation Checks
| date | member_count_match | price_count_match | valid_ma50_count_match | pct_above_50d_diff | valid_ma200_count_match | pct_above_200d_diff | advances_match | declines_match |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2009-05-04 | True | True | True | 0.0 | True | 0.0 | True | True |
| 2003-09-16 | True | True | True | 0.0 | True | 0.0 | True | True |
| 2011-08-23 | True | True | True | 0.0 | True | 0.0 | True | True |
| 2019-12-24 | True | True | True | 0.0 | True | 0.0 | True | True |
| 2000-05-10 | True | True | True | 0.0 | True | 0.0 | True | True |

## Historical Stress Sanity Rows
| period | date | SPY_close | SPY_pct_below_52w_high | sp500_pct_above_20d | sp500_pct_above_50d | sp500_pct_above_200d | sp500_ad_balance | sp500_pct_new_low_252d | SPY_fwd_maxdd_21d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2000-03_to_2000-04 | 2000-03-01 | 138.438 | -5.824489795918375 | 28.2 | 22.4 | 23.092369477911646 | 0.06418219461697723 | 10.240963855421686 | -0.0318805807992214 |
| 2000-03_to_2000-04 | 2000-03-30 | 148.688 | -3.1739623083836044 | 75.2 | 68.6 | 35.54216867469879 | 0.11293634496919917 | 1.606425702811245 | -0.1019388366979812 |
| 2000-03_to_2000-04 | 2000-04-28 | 145.094 | -5.51438506922286 | 52.4 | 69.6 | 47.09418837675351 | -0.21991701244813278 | 1.606425702811245 | -0.06267942065409327 |
| 2001-09 | 2001-09-04 | 113.42 | -25.026936627864703 | 38.0 | 37.75100401606426 | 45.45454545454545 | 0.18309859154929578 | 6.085192697768763 | -0.141161022805805 |
| 2001-09 | 2001-09-19 | 101.95 | -31.870276194358492 | 8.216432865731463 | 10.865191146881287 | 19.02834008097166 | -0.5587044534412956 | 21.341463414634145 | -0.042174710588380404 |
| 2001-09 | 2001-09-28 | 104.44 | -27.972413793103446 | 26.8 | 17.635270541082164 | 22.983870967741936 | 0.7616161616161616 | 1.0121457489878543 | -0.028205309734513295 |
| 2002-07 | 2002-07-01 | 97.03 | -21.831950374607267 | 21.6 | 17.4 | 41.2 | -0.6653225806451613 | 9.437751004016064 | -0.1949483280776797 |
| 2002-07 | 2002-07-17 | 90.74 | -25.992985890221032 | 10.6 | 3.8 | 11.8 | 0.020161290322580645 | 10.420841683366733 | -0.11891337775499744 |
| 2002-07 | 2002-07-31 | 91.16 | -25.650436342875782 | 54.6 | 16.6 | 19.919517102615693 | 0.030181086519114688 | 2.2132796780684103 | -0.08107004982908461 |
| 2007-08 | 2007-08-01 | 146.43 | -5.571677307022627 | 13.4 | 22.736418511066397 | 47.17741935483871 | 0.2808080808080808 | 6.262626262626263 | -0.05867088427771827 |
| 2007-08 | 2007-08-16 | 142.1 | -8.363964661120782 | 11.6 | 8.651911468812877 | 31.653225806451612 | 0.010101010101010102 | 6.8686868686868685 | -0.031081391344277343 |
| 2007-08 | 2007-08-31 | 147.59 | -4.823628038950146 | 63.4 | 33.6 | 43.75 | 0.8108651911468813 | 0.0 | -0.022063582714639263 |
| 2008-09_to_2009-03 | 2008-09-02 | 127.99 | -18.206799591002042 | 52.0 | 62.6 | 38.22937625754527 | 0.1646586345381526 | 2.0161290322580645 | -0.12493614616279203 |
| 2008-09_to_2009-03 | 2008-12-15 | 87.75 | -41.32397191574725 | 62.4 | 26.2 | 2.4193548387096775 | -0.596 | 1.4112903225806452 | -0.09736189203869816 |
| 2008-09_to_2009-03 | 2009-03-31 | 79.52 | -44.411045089129686 | 84.2 | 54.4 | 7.8 | 0.5040322580645161 | 0.0 | -0.04192478568299851 |
| 2010-05 | 2010-05-03 | 120.35 | -1.198587964863318 | 58.6 | 75.4 | 87.7755511022044 | 0.7142857142857143 | 0.0 | -0.10951440365750809 |
| 2010-05 | 2010-05-17 | 113.95 | -6.452672194401121 | 16.4 | 30.4 | 71.34268537074148 | 0.2591093117408907 | 0.8016032064128257 | -0.07424640195021326 |
| 2010-05 | 2010-05-28 | 109.37 | -10.2126262211641 | 15.8 | 12.4 | 55.31062124248497 | -0.7545271629778671 | 0.8016032064128257 | -0.06729796928347942 |
| 2011-08 | 2011-08-01 | 128.78 | -5.607271128051017 | 13.2 | 25.851703406813627 | 45.381526104417674 | -0.5560081466395111 | 4.618473895582329 | -0.12828478047497138 |
| 2011-08 | 2011-08-16 | 119.59 | -12.343326247892694 | 11.2 | 9.218436873747494 | 23.092369477911646 | -0.682092555331992 | 0.0 | -0.05874602552375974 |
| 2011-08 | 2011-08-31 | 122.22 | -10.415597742432025 | 95.8 | 28.857715430861724 | 33.333333333333336 | 0.5301204819277109 | 0.0 | -0.07183904982248146 |
| 2015-08 | 2015-08-03 | 209.79 | -1.7377049180327897 | 53.58565737051793 | 48.89336016096579 | 51.41129032258065 | -0.196 | 7.661290322580645 | -0.11073550034774093 |
| 2015-08 | 2015-08-17 | 210.59 | -1.3629976580796233 | 62.15139442231076 | 53.92354124748491 | 54.435483870967744 | 0.5676767676767677 | 0.8064516129032258 | -0.11073550034774093 |
| 2015-08 | 2015-08-31 | 197.67 | -7.414519906323191 | 12.749003984063744 | 15.090543259557345 | 28.225806451612904 | -0.564 | 0.4032258064516129 | -0.055833088451366475 |
| 2016-01 | 2016-01-04 | 201.02 | -5.845433255269317 | 24.8015873015873 | 25.89641434262948 | 36.82092555331992 | -0.6500994035785288 | 1.8108651911468814 | -0.07801907591459467 |
| 2016-01 | 2016-01-15 | 187.81 | -12.032786885245905 | 8.151093439363818 | 10.557768924302788 | 19.35483870967742 | -0.8087649402390438 | 22.177419354838708 | -0.056059705516510294 |
| 2016-01 | 2016-01-29 | 193.72 | -9.264637002341924 | 59.72222222222222 | 29.62226640159046 | 27.96780684104628 | 0.9246031746031746 | 0.4024144869215292 | -0.056059705516510294 |
| 2018-02 | 2018-02-01 | 281.58 | -1.7447135180403417 | 51.881188118811885 | 72.47524752475248 | 77.9324055666004 | -0.1746031746031746 | 2.589641434262948 | -0.08505685705379662 |
| 2018-02 | 2018-02-14 | 269.59 | -5.9285365343010765 | 23.762376237623762 | 40.396039603960396 | 66.00397614314116 | 0.6190476190476191 | 1.1952191235059761 | -0.036703118206354524 |
| 2018-02 | 2018-02-28 | 271.65 | -5.209714564868451 | 42.97029702970297 | 37.62376237623762 | 63.41948310139165 | -0.6819085487077535 | 3.187250996015936 | -0.07095587483905252 |
| 2018-12 | 2018-12-03 | 279.3 | -4.86409155937052 | 79.8019801980198 | 63.492063492063494 | 49.70178926441352 | 0.5247524752475248 | 0.3976143141153082 | -0.1559695119003497 |
| 2018-12 | 2018-12-17 | 255.36 | -13.018597997138759 | 4.158415841584159 | 15.277777777777779 | 24.055666003976143 | -0.8492063492063492 | 23.658051689860834 | -0.07684037523518294 |
| 2018-12 | 2018-12-31 | 249.92 | -14.87158525785135 | 14.257425742574258 | 10.714285714285714 | 20.07952286282306 | 0.6858846918489065 | 0.1988071570576541 | -0.023865089371138293 |
| 2020-02_to_2020-03 | 2020-02-03 | 324.12 | -2.358788974243109 | 36.83168316831683 | 48.118811881188115 | 68.78727634194831 | 0.4810379241516966 | 1.8 | -0.12437057128766849 |
| 2020-02_to_2020-03 | 2020-03-03 | 300.24 | -11.260861854938808 | 2.9702970297029703 | 9.108910891089108 | 33.59840954274354 | -0.8257425742574257 | 13.6 | -0.283005561305942 |
| 2020-02_to_2020-03 | 2020-03-31 | 257.75 | -23.819235088963765 | 28.91089108910891 | 4.158415841584159 | 8.712871287128714 | -0.5595238095238095 | 0.5964214711729622 | -0.04744540828172639 |
| 2022-01_to_2022-10 | 2022-01-03 | 477.71 | 0.0 | 79.20792079207921 | 70.6930693069307 | 73.21428571428571 | 0.0019801980198019802 | 0.0 | -0.09727540746509433 |
| 2022-01_to_2022-10 | 2022-06-02 | 417.39 | -12.626907538046094 | 86.9047619047619 | 43.05555555555556 | 34.990059642147116 | 0.7211155378486056 | 0.1988071570576541 | -0.12156401774130898 |
| 2022-01_to_2022-10 | 2022-10-31 | 386.21 | -19.15387996901886 | 86.65338645418326 | 61.95219123505976 | 35.528942115768466 | -0.408 | 0.998003992015968 | -0.03935833882017492 |

## Null Counts By Major Feature Family
### data_quality
| field | null_count |
| --- | --- |
| date | 0 |
| sp500_member_count | 0 |
| sp500_price_count | 0 |
| sp500_price_coverage_pct | 0 |
| sp500_valid_ma20_count | 0 |
| sp500_valid_ma50_count | 0 |
| sp500_valid_ma100_count | 0 |
| sp500_valid_ma200_count | 0 |
| sp500_ma20_coverage_pct | 0 |
| sp500_ma50_coverage_pct | 0 |
| sp500_ma100_coverage_pct | 0 |
| sp500_ma200_coverage_pct | 0 |
| sp500_valid_highlow20_count | 0 |
| sp500_valid_highlow50_count | 0 |
| sp500_valid_252d_count | 0 |
| breadth_data_quality_ok | 0 |
| sp500_valid_ad_count | 0 |
| sp500_valid_return_1d_count | 0 |
| sp500_valid_return_5d_count | 0 |
| sp500_valid_return_20d_count | 0 |

### market_prices
| field | null_count |
| --- | --- |
| SPY_close | 0 |
| QQQ_close | 237 |
| IWM_close | 545 |
| RSP_close | 1278 |
| SPY_return_1d | 0 |
| QQQ_return_1d | 238 |
| IWM_return_1d | 546 |
| RSP_return_1d | 1279 |
| sp500_avg_return_1d | 0 |
| sp500_median_return_1d | 0 |

### ma_breadth
| field | null_count |
| --- | --- |
| sp500_pct_above_20d | 0 |
| sp500_pct_above_50d | 0 |
| sp500_pct_above_100d | 38 |
| sp500_pct_above_200d | 138 |
| sp500_pct_above_20d_z | 252 |
| sp500_pct_above_20d_pctile | 252 |
| sp500_pct_above_50d_z | 252 |
| sp500_pct_above_50d_pctile | 252 |
| sp500_pct_above_200d_z | 390 |
| sp500_pct_above_200d_pctile | 390 |
| SPY_within_3pct_high_and_sp500_pct_above_20d_down_10pp_10d | 0 |
| SPY_within_3pct_high_and_sp500_pct_above_20d_down_20pp_10d | 0 |
| SPY_within_3pct_high_and_sp500_pct_above_20d_down_30pp_10d | 0 |
| SPY_within_3pct_high_and_sp500_pct_above_50d_down_10pp_10d | 0 |
| SPY_within_3pct_high_and_sp500_pct_above_50d_down_20pp_10d | 0 |
| SPY_within_3pct_high_and_sp500_pct_above_50d_down_30pp_10d | 0 |

### distance
| field | null_count |
| --- | --- |
| sp500_avg_dist_20d | 0 |
| sp500_median_dist_20d | 0 |
| sp500_avg_dist_50d | 0 |
| sp500_median_dist_50d | 0 |
| sp500_avg_dist_100d | 38 |
| sp500_median_dist_100d | 38 |
| sp500_avg_dist_200d | 138 |
| sp500_median_dist_200d | 138 |
| SPY_dist_20d | 0 |
| SPY_dist_50d | 0 |
| SPY_dist_200d | 138 |

### advance_decline
| field | null_count |
| --- | --- |
| sp500_advances | 0 |
| sp500_declines | 0 |
| sp500_net_advances | 0 |
| sp500_ad_balance | 0 |
| sp500_adl_raw | 0 |
| sp500_adl_normalized | 0 |
| sp500_adl_slope_5d | 4 |
| sp500_adl_slope_10d | 9 |
| sp500_adl_slope_20d | 19 |
| sp500_adl_slope_50d | 49 |
| sp500_ad_balance_chg_1d | 1 |
| sp500_ad_balance_chg_3d | 3 |
| sp500_ad_balance_chg_5d | 5 |
| sp500_ad_balance_chg_10d | 10 |
| sp500_ad_balance_chg_20d | 20 |
| sp500_adl_slope_20d_chg_1d | 20 |
| sp500_adl_slope_20d_chg_3d | 22 |
| sp500_adl_slope_20d_chg_5d | 24 |
| sp500_adl_slope_20d_chg_10d | 29 |
| sp500_adl_slope_20d_chg_20d | 39 |
| sp500_adl_slope_20d_z | 271 |
| sp500_adl_slope_20d_pctile | 271 |
| sp500_ad_balance_z | 252 |
| sp500_ad_balance_pctile | 252 |

### new_high_low
| field | null_count |
| --- | --- |
| sp500_new_highs_20d | 0 |
| sp500_new_lows_20d | 0 |
| sp500_pct_new_high_20d | 0 |
| sp500_pct_new_low_20d | 0 |
| sp500_nhnl_20d | 0 |
| sp500_normalized_nhnl_20d | 0 |
| sp500_new_highs_50d | 0 |
| sp500_new_lows_50d | 0 |
| sp500_pct_new_high_50d | 0 |
| sp500_pct_new_low_50d | 0 |
| sp500_nhnl_50d | 0 |
| sp500_normalized_nhnl_50d | 0 |
| sp500_new_highs_252d | 0 |
| sp500_new_lows_252d | 0 |
| sp500_pct_new_high_252d | 190 |
| sp500_pct_new_low_252d | 190 |
| sp500_nhnl_252d | 0 |
| sp500_normalized_nhnl_252d | 190 |
| sp500_pct_new_low_252d_chg_1d | 191 |
| sp500_pct_new_low_252d_chg_3d | 193 |
| sp500_pct_new_low_252d_chg_5d | 195 |
| sp500_pct_new_low_252d_chg_10d | 200 |
| sp500_pct_new_low_252d_chg_20d | 210 |
| sp500_normalized_nhnl_252d_chg_1d | 191 |
| sp500_normalized_nhnl_252d_chg_3d | 193 |
| sp500_normalized_nhnl_252d_chg_5d | 195 |
| sp500_normalized_nhnl_252d_chg_10d | 200 |
| sp500_normalized_nhnl_252d_chg_20d | 210 |
| sp500_pct_new_low_252d_z | 442 |
| sp500_pct_new_low_252d_pctile | 442 |
| sp500_normalized_nhnl_252d_z | 442 |
| sp500_normalized_nhnl_252d_pctile | 442 |

### velocity
| field | null_count |
| --- | --- |
| sp500_pct_above_20d_chg_1d | 1 |
| sp500_pct_above_20d_chg_3d | 3 |
| sp500_pct_above_20d_chg_5d | 5 |
| sp500_pct_above_20d_chg_10d | 10 |
| sp500_pct_above_20d_chg_20d | 20 |
| sp500_pct_above_50d_chg_1d | 1 |
| sp500_pct_above_50d_chg_3d | 3 |
| sp500_pct_above_50d_chg_5d | 5 |
| sp500_pct_above_50d_chg_10d | 10 |
| sp500_pct_above_50d_chg_20d | 20 |
| sp500_pct_above_100d_chg_1d | 39 |
| sp500_pct_above_100d_chg_3d | 41 |
| sp500_pct_above_100d_chg_5d | 43 |
| sp500_pct_above_100d_chg_10d | 48 |
| sp500_pct_above_100d_chg_20d | 58 |
| sp500_pct_above_200d_chg_1d | 139 |
| sp500_pct_above_200d_chg_3d | 141 |
| sp500_pct_above_200d_chg_5d | 143 |
| sp500_pct_above_200d_chg_10d | 148 |
| sp500_pct_above_200d_chg_20d | 158 |
| sp500_ad_balance_chg_1d | 1 |
| sp500_ad_balance_chg_3d | 3 |
| sp500_ad_balance_chg_5d | 5 |
| sp500_ad_balance_chg_10d | 10 |
| sp500_ad_balance_chg_20d | 20 |
| sp500_adl_slope_20d_chg_1d | 20 |
| sp500_adl_slope_20d_chg_3d | 22 |
| sp500_adl_slope_20d_chg_5d | 24 |
| sp500_adl_slope_20d_chg_10d | 29 |
| sp500_adl_slope_20d_chg_20d | 39 |
| sp500_pct_positive_20d_chg_1d | 1 |
| sp500_pct_positive_20d_chg_3d | 3 |
| sp500_pct_positive_20d_chg_5d | 5 |
| sp500_pct_positive_20d_chg_10d | 10 |
| sp500_pct_positive_20d_chg_20d | 20 |
| sp500_pct_new_low_252d_chg_1d | 191 |
| sp500_pct_new_low_252d_chg_3d | 193 |
| sp500_pct_new_low_252d_chg_5d | 195 |
| sp500_pct_new_low_252d_chg_10d | 200 |
| sp500_pct_new_low_252d_chg_20d | 210 |
| sp500_normalized_nhnl_252d_chg_1d | 191 |
| sp500_normalized_nhnl_252d_chg_3d | 193 |
| sp500_normalized_nhnl_252d_chg_5d | 195 |
| sp500_normalized_nhnl_252d_chg_10d | 200 |
| sp500_normalized_nhnl_252d_chg_20d | 210 |
| sp500_pct_above_20d_chg_5d_z | 257 |
| sp500_pct_above_20d_chg_5d_pctile | 257 |
| sp500_pct_above_50d_chg_5d_z | 257 |
| sp500_pct_above_50d_chg_5d_pctile | 257 |
| sp500_pct_above_50d_chg_10d_z | 262 |
| sp500_pct_above_50d_chg_10d_pctile | 262 |
| sp500_pct_above_200d_chg_10d_z | 400 |
| sp500_pct_above_200d_chg_10d_pctile | 400 |

### acceleration
| field | null_count |
| --- | --- |
| sp500_pct_above_20d_accel_5d | 10 |
| sp500_pct_above_20d_accel_10d | 20 |
| sp500_pct_above_50d_accel_5d | 10 |
| sp500_pct_above_50d_accel_10d | 20 |
| sp500_pct_above_200d_accel_5d | 148 |
| sp500_pct_above_200d_accel_10d | 158 |

### normalization
| field | null_count |
| --- | --- |
| sp500_pct_above_20d_z | 252 |
| sp500_pct_above_20d_pctile | 252 |
| sp500_pct_above_50d_z | 252 |
| sp500_pct_above_50d_pctile | 252 |
| sp500_pct_above_200d_z | 390 |
| sp500_pct_above_200d_pctile | 390 |
| sp500_pct_above_20d_chg_5d_z | 257 |
| sp500_pct_above_20d_chg_5d_pctile | 257 |
| sp500_pct_above_50d_chg_5d_z | 257 |
| sp500_pct_above_50d_chg_5d_pctile | 257 |
| sp500_pct_above_50d_chg_10d_z | 262 |
| sp500_pct_above_50d_chg_10d_pctile | 262 |
| sp500_pct_above_200d_chg_10d_z | 400 |
| sp500_pct_above_200d_chg_10d_pctile | 400 |
| sp500_adl_slope_20d_z | 271 |
| sp500_adl_slope_20d_pctile | 271 |
| sp500_ad_balance_z | 252 |
| sp500_ad_balance_pctile | 252 |
| sp500_pct_new_low_252d_z | 442 |
| sp500_pct_new_low_252d_pctile | 442 |
| sp500_normalized_nhnl_252d_z | 442 |
| sp500_normalized_nhnl_252d_pctile | 442 |

### outcomes
| field | null_count |
| --- | --- |
| SPY_fwd_return_5d | 5 |
| SPY_fwd_return_10d | 10 |
| SPY_fwd_return_21d | 21 |
| SPY_fwd_return_42d | 42 |
| SPY_fwd_return_63d | 63 |
| QQQ_fwd_return_5d | 242 |
| QQQ_fwd_return_10d | 247 |
| QQQ_fwd_return_21d | 258 |
| QQQ_fwd_return_42d | 279 |
| QQQ_fwd_return_63d | 300 |
| IWM_fwd_return_5d | 550 |
| IWM_fwd_return_10d | 555 |
| IWM_fwd_return_21d | 566 |
| IWM_fwd_return_42d | 587 |
| IWM_fwd_return_63d | 608 |
| SPY_fwd_maxdd_5d | 5 |
| SPY_fwd_maxdd_10d | 10 |
| SPY_fwd_maxdd_21d | 21 |
| SPY_fwd_maxdd_42d | 42 |
| SPY_fwd_maxdd_63d | 63 |
| QQQ_fwd_maxdd_5d | 242 |
| QQQ_fwd_maxdd_10d | 247 |
| QQQ_fwd_maxdd_21d | 258 |
| QQQ_fwd_maxdd_42d | 279 |
| QQQ_fwd_maxdd_63d | 300 |
| IWM_fwd_maxdd_5d | 550 |
| IWM_fwd_maxdd_10d | 555 |
| IWM_fwd_maxdd_21d | 566 |
| IWM_fwd_maxdd_42d | 587 |
| IWM_fwd_maxdd_63d | 608 |
| SPY_fwd5_dd_ge_5pct | 0 |
| SPY_fwd5_dd_ge_7_5pct | 0 |
| SPY_fwd5_dd_ge_10pct | 0 |
| SPY_fwd10_dd_ge_5pct | 0 |
| SPY_fwd10_dd_ge_7_5pct | 0 |
| SPY_fwd10_dd_ge_10pct | 0 |
| SPY_fwd21_dd_ge_5pct | 0 |
| SPY_fwd21_dd_ge_7_5pct | 0 |
| SPY_fwd21_dd_ge_10pct | 0 |
| SPY_fwd42_dd_ge_5pct | 0 |
| SPY_fwd42_dd_ge_7_5pct | 0 |
| SPY_fwd42_dd_ge_10pct | 0 |
| SPY_fwd63_dd_ge_5pct | 0 |
| SPY_fwd63_dd_ge_7_5pct | 0 |
| SPY_fwd63_dd_ge_10pct | 0 |
| QQQ_fwd5_dd_ge_5pct | 0 |
| QQQ_fwd5_dd_ge_7_5pct | 0 |
| QQQ_fwd5_dd_ge_10pct | 0 |
| QQQ_fwd10_dd_ge_5pct | 0 |
| QQQ_fwd10_dd_ge_7_5pct | 0 |
| QQQ_fwd10_dd_ge_10pct | 0 |
| QQQ_fwd21_dd_ge_5pct | 0 |
| QQQ_fwd21_dd_ge_7_5pct | 0 |
| QQQ_fwd21_dd_ge_10pct | 0 |
| QQQ_fwd42_dd_ge_5pct | 0 |
| QQQ_fwd42_dd_ge_7_5pct | 0 |
| QQQ_fwd42_dd_ge_10pct | 0 |
| QQQ_fwd63_dd_ge_5pct | 0 |
| QQQ_fwd63_dd_ge_7_5pct | 0 |
| QQQ_fwd63_dd_ge_10pct | 0 |
| IWM_fwd5_dd_ge_5pct | 0 |
| IWM_fwd5_dd_ge_7_5pct | 0 |
| IWM_fwd5_dd_ge_10pct | 0 |
| IWM_fwd10_dd_ge_5pct | 0 |
| IWM_fwd10_dd_ge_7_5pct | 0 |
| IWM_fwd10_dd_ge_10pct | 0 |
| IWM_fwd21_dd_ge_5pct | 0 |
| IWM_fwd21_dd_ge_7_5pct | 0 |
| IWM_fwd21_dd_ge_10pct | 0 |
| IWM_fwd42_dd_ge_5pct | 0 |
| IWM_fwd42_dd_ge_7_5pct | 0 |
| IWM_fwd42_dd_ge_10pct | 0 |
| IWM_fwd63_dd_ge_5pct | 0 |
| IWM_fwd63_dd_ge_7_5pct | 0 |
| IWM_fwd63_dd_ge_10pct | 0 |

## Sector Breadth
- `created`: True
- `reason`: usable
- `caveat`: Sharadar TICKERS sector labels are security-master metadata from the download, not point-in-time historical GICS classifications.
### Sector Coverage
| membership_rows | rows_with_sector | pct_rows_with_sector | membership_tickers | tickers_with_sector |
| --- | --- | --- | --- | --- |
| 3580605 | 3580178 | 99.98807464101736 | 1161 | 1160 |
### Sector Counts
| sector | tickers | membership_rows |
| --- | --- | --- |
| Financial Services | 161 | 511781 |
| Technology | 185 | 491379 |
| Industrials | 138 | 476966 |
| Consumer Cyclical | 139 | 434785 |
| Healthcare | 122 | 397205 |
| Consumer Defensive | 82 | 303380 |
| Utilities | 62 | 227468 |
| Energy | 76 | 218068 |
| Basic Materials | 81 | 207400 |
| Communication Services | 71 | 175178 |
| Real Estate | 43 | 136568 |
| __missing__ | 1 | 427 |
