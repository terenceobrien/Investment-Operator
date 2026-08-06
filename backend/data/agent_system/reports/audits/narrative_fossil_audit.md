# Narrative Fossil Audit

Backend-only scan for retired narrative scenario IDs, `narrative_v0`, and legacy daily analogue imports.

| File | Line | Matched String | Classification | Justification |
| --- | ---: | --- | --- | --- |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 11 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 13 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 46 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 191 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 334 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 474 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 475 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 614 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 615 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/behavioral_scenarios.yaml | 757 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/current_conditions.yaml | 65 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/config/current_regime.yaml | 11 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/diagnostics/input_matrix.py | 465 | `src.analysis.analogues` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/fixtures/macro_forecast_sample.json | 6 | `reopening_soft_landing` | historical_artifact | Stored fixture or generated artifact reference, not an executable forecast path. |
| backend/src/agent_system/fixtures/macro_forecast_sample.json | 7 | `sticky_late_cycle_ai` | historical_artifact | Stored fixture or generated artifact reference, not an executable forecast path. |
| backend/src/agent_system/fixtures/macro_forecast_sample.json | 8 | `oil_inflation_tail` | historical_artifact | Stored fixture or generated artifact reference, not an executable forecast path. |
| backend/src/agent_system/fixtures/macro_forecast_sample.json | 9 | `late_cycle_risk_off` | historical_artifact | Stored fixture or generated artifact reference, not an executable forecast path. |
| backend/src/agent_system/fixtures/macro_forecast_sample.json | 10 | `ai_capex_rollover` | historical_artifact | Stored fixture or generated artifact reference, not an executable forecast path. |
| backend/src/agent_system/forecasting/current_regime_export.py | 90 | `reopening_soft_landing` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 91 | `sticky_late_cycle_ai` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 92 | `oil_inflation_tail` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 93 | `late_cycle_risk_off` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 94 | `ai_capex_rollover` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 176 | `late_cycle_risk_off` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 177 | `ai_capex_rollover` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/current_regime_export.py | 248 | `oil_inflation_tail` | reader_compat | Label/display compatibility for older current-regime artifacts. |
| backend/src/agent_system/forecasting/historical_calibration.py | 24 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 25 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 26 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 27 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 28 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 127 | `src.analysis.analogues` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 241 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 244 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 250 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 254 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 267 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 272 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 284 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 286 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 292 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 294 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 299 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 301 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 310 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 313 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 317 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 319 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 349 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 365 | `src.analysis.analogues` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 496 | `src.analysis.rolling_composite` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 559 | `src.analysis.analogues` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 697 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/historical_calibration.py | 923 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 458 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 459 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 460 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 471 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 472 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 473 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 520 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 521 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 522 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 531 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 532 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 533 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 569 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 570 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 571 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 583 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 584 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 585 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 595 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 596 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 597 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 639 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 640 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 641 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 650 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 651 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 706 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 707 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 708 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 718 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 719 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 729 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 730 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 827 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 828 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 829 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 830 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 839 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 840 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 841 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 849 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 850 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 851 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 860 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 861 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 942 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 943 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 993 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 994 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1019 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1020 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1055 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1056 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1158 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1160 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1188 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1189 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1190 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1199 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1200 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1201 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1230 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1235 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1236 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1272 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1273 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1274 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1280 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1281 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1288 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1291 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1298 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1299 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1305 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1306 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1312 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1315 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1320 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1323 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1329 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1330 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1334 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1367 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1368 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1375 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1376 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1385 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1388 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1393 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1395 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1399 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1400 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1408 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1414 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1415 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1419 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1424 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1481 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1482 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1483 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1493 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1494 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1495 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1529 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1532 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1538 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1539 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1543 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1548 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1551 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1556 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1559 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1564 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1567 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1787 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1789 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1793 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1795 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1799 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1801 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1805 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1807 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1811 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1813 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1830 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1831 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1833 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1834 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1841 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1842 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1844 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1845 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1852 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1854 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1855 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1863 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1865 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1873 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1874 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1876 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1877 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1886 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1904 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1924 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1926 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1944 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1948 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/input_signals.py | 1948 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 482 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 483 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 484 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 485 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 486 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 577 | `sticky_late_cycle_ai` | dead_code | Surrounding code marks this path as legacy or fail-loud after the two_source_v1 rewire. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 590 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 603 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 616 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_forecast_runner.py | 629 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_scenario_source.py | 51 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_scenario_source.py | 266 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_scenario_source.py | 270 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_scenario_source.py | 376 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/macro_scenario_source.py | 596 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 45 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 59 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 73 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 87 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 101 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 391 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 394 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 437 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 438 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 439 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 440 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/forecasting/theme_exposure_matrix.py | 441 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/orchestration/run_research_cycle.py | 344 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/orchestration/run_research_cycle.py | 451 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/reporting/macro_forecast_docx.py | 1873 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/reporting/macro_forecast_docx.py | 1874 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/reporting/macro_forecast_docx.py | 1875 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/reporting/macro_forecast_docx.py | 1876 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/reporting/macro_forecast_docx.py | 1877 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/scenarios/types.py | 11 | `reopening_soft_landing` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/scenarios/types.py | 12 | `sticky_late_cycle_ai` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/scenarios/types.py | 13 | `oil_inflation_tail` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/scenarios/types.py | 14 | `late_cycle_risk_off` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/scenarios/types.py | 15 | `ai_capex_rollover` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/schemas/macro_forecast.py | 78 | `reopening_soft_landing` | reader_compat | Reader compatibility surface for old artifacts; not a newly produced probability path. |
| backend/src/agent_system/schemas/macro_forecast.py | 79 | `sticky_late_cycle_ai` | reader_compat | Reader compatibility surface for old artifacts; not a newly produced probability path. |
| backend/src/agent_system/schemas/macro_forecast.py | 80 | `oil_inflation_tail` | reader_compat | Reader compatibility surface for old artifacts; not a newly produced probability path. |
| backend/src/agent_system/schemas/macro_forecast.py | 81 | `late_cycle_risk_off` | reader_compat | Reader compatibility surface for old artifacts; not a newly produced probability path. |
| backend/src/agent_system/schemas/macro_forecast.py | 82 | `ai_capex_rollover` | reader_compat | Reader compatibility surface for old artifacts; not a newly produced probability path. |
| backend/src/agent_system/schemas/macro_forecast.py | 620 | `late_cycle_risk_off` | reader_compat | Reader compatibility surface for old artifacts; not a newly produced probability path. |
| backend/src/agent_system/services/scenario_compatibility.py | 13 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/services/scenario_compatibility.py | 16 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/services/scenario_compatibility.py | 58 | `narrative_v0` | dead_code | Surrounding code marks this path as legacy or fail-loud after the two_source_v1 rewire. |
| backend/src/agent_system/services/scenario_compatibility.py | 66 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/services/scenario_compatibility.py | 70 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/services/scenario_compatibility.py | 75 | `narrative_v0` | live_code_path | Backend executable code still references a retired narrative marker and needs owner review. |
| backend/src/agent_system/services/scenario_translation.py | 14 | `reopening_soft_landing` | live_code_path | Legitimate Monte Carlo boundary translating legacy narrative inputs into behavioral IDs. |
| backend/src/agent_system/services/scenario_translation.py | 15 | `sticky_late_cycle_ai` | live_code_path | Legitimate Monte Carlo boundary translating legacy narrative inputs into behavioral IDs. |
| backend/src/agent_system/services/scenario_translation.py | 16 | `oil_inflation_tail` | live_code_path | Legitimate Monte Carlo boundary translating legacy narrative inputs into behavioral IDs. |
| backend/src/agent_system/services/scenario_translation.py | 17 | `late_cycle_risk_off` | live_code_path | Legitimate Monte Carlo boundary translating legacy narrative inputs into behavioral IDs. |
| backend/src/agent_system/services/scenario_translation.py | 21 | `ai_capex_rollover` | live_code_path | Legitimate Monte Carlo boundary translating legacy narrative inputs into behavioral IDs. |
| backend/src/agent_system/tests/test_adapter_regime.py | 180 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_adapter_regime.py | 181 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_adapter_regime.py | 182 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_adapter_regime.py | 183 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_adapter_regime.py | 184 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_adapter_regime.py | 191 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_analogue_horizons.py | 8 | `src.analysis.rolling_composite` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_current_regime_export.py | 94 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_current_regime_export.py | 95 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_current_regime_export.py | 96 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_current_regime_export.py | 97 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_current_regime_export.py | 98 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_detailed_analogues.py | 14 | `src.analysis.rolling_composite` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_exposure_enrichment.py | 58 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_exposure_enrichment.py | 64 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_exposure_enrichment.py | 70 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_exposure_enrichment.py | 70 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_exposure_enrichment.py | 106 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_exposure_enrichment.py | 107 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_macro_forecast.py | 176 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_narrative_fossil_audit.py | 14 | `src.analysis.analogues` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_narrative_fossil_audit.py | 15 | `src.analysis.rolling_composite` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_narrative_fossil_audit.py | 118 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 96 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 97 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 98 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 99 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 100 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 107 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 108 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 109 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 110 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 111 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 299 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 300 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 301 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 302 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 303 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 326 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 327 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 328 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 329 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 330 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 360 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 361 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 362 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 363 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 364 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 387 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 388 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 389 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 390 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 400 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 401 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 412 | `reopening_soft_landing` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 413 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 414 | `oil_inflation_tail` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 415 | `late_cycle_risk_off` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 416 | `ai_capex_rollover` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/agent_system/tests/test_scenarios.py | 421 | `sticky_late_cycle_ai` | test_fixture | Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy. |
| backend/src/analysis/analogues.py | 41 | `src.analysis.analogues` | dead_code | Surrounding code marks this path as legacy or fail-loud after the two_source_v1 rewire. |
| backend/src/analysis/rolling_composite.py | 23 | `from .analogues import` | dead_code | Legacy daily analogue implementation retained outside the live behavioral macro probability path. |
| backend/src/analysis/rolling_composite.py | 54 | `src.analysis.rolling_composite` | dead_code | Surrounding code marks this path as legacy or fail-loud after the two_source_v1 rewire. |
