MacBook-Pro-10:backend terenceobrien$ python3 -m src.agent_system.forecasting.scenario_classifier.cli run-validation

Validation mode: t0_change
 start               expected               assigned   margin  correct  must_pass                      note
2008Q1   credit_led_recession growth_scare_no_credit 0.530330    False       True                       GFC
2021Q3        inflation_shock        inflation_shock 0.497925     True       True      post-COVID inflation
2018Q4 growth_scare_no_credit expansion_disinflation 0.710750    False      False          equity-led scare
2015Q3 growth_scare_no_credit   late_cycle_expansion 0.210545    False      False manufacturing/China scare
2017Q1 expansion_disinflation expansion_disinflation 0.374467     True      False       synchronized growth
1978Q1            stagflation   late_cycle_expansion 0.403064    False      False               pre-Volcker
2006Q3   late_cycle_expansion expansion_disinflation 1.122355    False      False          housing-flavored

Miss: 2008Q1 expected=credit_led_recession assigned=growth_scare_no_credit
scenario       credit_led_recession  growth_scare_no_credit
variable                                                   
activity                      0.809                   1.197
core_pce                      1.746                   1.778
credit_spread                35.088                  25.917
fed_funds                     1.496                   2.233
lur                           1.982                   3.348
ten_year                      0.828                   0.888

Miss: 2018Q4 expected=growth_scare_no_credit assigned=expansion_disinflation
scenario       expansion_disinflation  growth_scare_no_credit
variable                                                     
activity                        0.096                   1.495
core_pce                        0.015                   0.327
credit_spread                   0.248                   0.027
fed_funds                       0.077                   0.420
lur                             0.026                   2.135
ten_year                        3.025                   2.242

Miss: 2015Q3 expected=growth_scare_no_credit assigned=late_cycle_expansion
scenario       growth_scare_no_credit  late_cycle_expansion
variable                                                   
activity                        0.390                 0.245
core_pce                        0.368                 0.098
credit_spread                   0.626                 0.723
fed_funds                       0.896                 0.013
lur                             2.086                 0.012
ten_year                        0.320                 1.099

Miss: 1978Q1 expected=stagflation assigned=late_cycle_expansion
scenario       late_cycle_expansion  stagflation
variable                                        
activity                      0.951        4.475
core_pce                      0.041        1.744
credit_spread                 0.245        0.924
fed_funds                     4.198        6.249
lur                           0.172        3.369
ten_year                      1.404        1.943

Miss: 2006Q3 expected=late_cycle_expansion assigned=expansion_disinflation
scenario       expansion_disinflation  late_cycle_expansion
variable                                                   
activity                        0.094                 0.116
core_pce                        0.057                 2.386
credit_spread                   0.130                 0.110
fed_funds                       0.004                 0.140
lur                             0.023                 0.014
ten_year                        0.096                 0.323

Validation mode: trailing_trend
 start               expected               assigned   margin  correct  must_pass                      note
2008Q1   credit_led_recession   credit_led_recession 0.957648     True       True                       GFC
2021Q3        inflation_shock        inflation_shock 0.251307     True       True      post-COVID inflation
2018Q4 growth_scare_no_credit growth_scare_no_credit 0.297894     True      False          equity-led scare
2015Q3 growth_scare_no_credit growth_scare_no_credit 0.126870     True      False manufacturing/China scare
2017Q1 expansion_disinflation expansion_disinflation 0.407789     True      False       synchronized growth
1978Q1            stagflation   late_cycle_expansion 0.452819    False      False               pre-Volcker
2006Q3   late_cycle_expansion growth_scare_no_credit 0.131344    False      False          housing-flavored

Miss: 1978Q1 expected=stagflation assigned=late_cycle_expansion
scenario       late_cycle_expansion  stagflation
variable                                        
activity                      1.283        5.180
core_pce                      0.380        3.317
credit_spread                 0.645        0.180
fed_funds                     3.377        5.245
lur                           0.047        2.145
ten_year                      3.971        4.914

Miss: 2006Q3 expected=late_cycle_expansion assigned=growth_scare_no_credit
scenario       growth_scare_no_credit  late_cycle_expansion
variable                                                   
activity                        0.656                 0.145
core_pce                        0.680                 2.773
credit_spread                   0.344                 0.486
fed_funds                       0.654                 3.413
lur                             0.757                 0.338
ten_year                        0.153                 0.965

Mode disagreement notes:
  2008Q1: t0_change=growth_scare_no_credit, trailing_trend=credit_led_recession
  2018Q4: t0_change=expansion_disinflation, trailing_trend=growth_scare_no_credit
  2015Q3: t0_change=late_cycle_expansion, trailing_trend=growth_scare_no_credit
  2006Q3: t0_change=expansion_disinflation, trailing_trend=growth_scare_no_credit
t0_change: correct=2/7 must_pass_ok=False
trailing_trend: correct=5/7 must_pass_ok=True

FINAL VERDICT: FAIL
((venv) ) MacBook-Pro-10:backend terenceobrien$ python3 -m src.agent_system.forecasting.bvar_ensemble.cli fit
Wrote posterior: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/bvar_cache/posterior_20260715T052111Z.npz
Wrote summary: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/bvar_cache/posterior_20260715T052111Z_summary.json
Largest companion eigenvalue modulus: 0.9547
((venv) ) MacBook-Pro-10:backend terenceobrien$ python3 -m src.agent_system.forecasting.bvar_ensemble.cli validate
BVAR ensemble validation OK
  posterior: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/bvar_cache/posterior_20260715T052111Z.npz
  BVAR cache: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/bvar_cache
  classifier cache: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/classifier_cache
  active classifier variables: activity, lur, core_pce, credit_spread, fed_funds, ten_year
  spine bounds: {'activity': (-10.0, 15.0), 'lur': (1.5, 20.0), 'core_pce': (-3.0, 15.0), 'credit_spread': (0.2, 10.0), 'fed_funds': (0.0, 25.0), 'ten_year': (0.0, 20.0), 'nfci': (-1.5, 6.0)}
((venv) ) MacBook-Pro-10:backend terenceobrien$ python3 -m src.agent_system.forecasting.bvar_ensemble.cli forecast --shock-dist student_t
Wrote forecast: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/bvar_cache/forecast_2026Q1_20260715T052204Z.json
Wrote classifier paths: /Users/terenceobrien/AI_Financial_Operator/data/agent_system/bvar_cache/forecast_2026Q1_20260715T052204Z_paths.parquet
BVAR forecast as of 2026Q1
Scenario probabilities (hard primary, soft secondary):
  late_cycle_expansion             hard=0.352 soft=0.296
  growth_scare_no_credit           hard=0.310 soft=0.277
  expansion_disinflation           hard=0.242 soft=0.266
  inflation_shock                  hard=0.054 soft=0.092
  stagflation                      hard=0.039 soft=0.067
  credit_led_recession             hard=0.003 soft=0.003
Validity: rejections=1229 redraws=1229 clips=0 rejection_rate=12.29%
WARNING: BVAR simulation rejection rate exceeds configured threshold; the residual covariance and registry bounds may disagree.
Tail flags: none