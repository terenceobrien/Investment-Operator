import json
from pathlib import Path

CYCLE_ID = "b9146956-516c-4619-8b47-8d93264b7696"
OUT = Path("/tmp/maturity_walls_audit_data_v2.json")

all_records = []
with open("data/agent_system/schema_records.jsonl") as f:
    for line in f:
        if not line.strip():
            continue
        all_records.append(json.loads(line))

# Find ALL records with direct cycle_id linkage
direct_cycle_records = [r for r in all_records if r["payload_json"].get("cycle_id") == CYCLE_ID]

# Find the ThematicMap to get all candidate tickers
thematic_maps = [r for r in all_records if r["schema_type"] == "ThematicMap"]
target_thematic = None
for tm in thematic_maps:
    sp = tm["payload_json"].get("source_priority", {})
    if sp.get("theme", "").startswith("2027-2028 maturity-wall"):
        target_thematic = tm
        break

candidate_tickers = []
if target_thematic:
    candidate_tickers = [c["ticker"] for c in target_thematic["payload_json"].get("candidates", [])]

# Find ALL TradeIdeas matching these tickers in a recent timewindow
trade_ideas_window = []
for r in all_records:
    if r["schema_type"] != "TradeIdea":
        continue
    if r["payload_json"].get("underlying") not in candidate_tickers:
        continue
    # Cycle window: 21:14 to 21:22 UTC on 2026-05-31
    created = r.get("created_at", "")
    if "2026-05-31T21:1" in created or "2026-05-31T21:2" in created:
        trade_ideas_window.append(r)

# Find FundamentalScreen records in the same window
fundamental_screens = [
    r for r in all_records
    if r["schema_type"] == "FundamentalScreen"
    and ("2026-05-31T21:1" in r.get("created_at", "") or "2026-05-31T21:2" in r.get("created_at", ""))
]

# Find Conviction records in the same window
convictions = [
    r for r in all_records
    if r["schema_type"] == "Conviction"
    and ("2026-05-31T21:1" in r.get("created_at", "") or "2026-05-31T21:2" in r.get("created_at", ""))
]

# Find NarrativeAnalysis records in the same window
narratives = [
    r for r in all_records
    if r["schema_type"] == "NarrativeAnalysis"
    and ("2026-05-31T21:1" in r.get("created_at", "") or "2026-05-31T21:2" in r.get("created_at", ""))
]

# Count all schema types in the window for completeness
window_types = {}
for r in all_records:
    if "2026-05-31T21:1" in r.get("created_at", "") or "2026-05-31T21:2" in r.get("created_at", ""):
        t = r["schema_type"]
        window_types[t] = window_types.get(t, 0) + 1

output = {
    "cycle_id": CYCLE_ID,
    "candidate_tickers_from_thematic_map": candidate_tickers,
    "trade_ideas_in_window": trade_ideas_window,
    "fundamental_screens_in_window": fundamental_screens,
    "convictions_in_window": convictions,
    "narratives_in_window": narratives,
    "window_schema_type_counts": window_types,
    "_counts": {
        "candidates_expected": len(candidate_tickers),
        "trade_ideas_found": len(trade_ideas_window),
        "fundamental_screens_found": len(fundamental_screens),
        "convictions_found": len(convictions),
        "narratives_found": len(narratives),
    },
}

OUT.write_text(json.dumps(output, indent=2))
print("Wrote", OUT)
print("Counts:", output["_counts"])
print("Window schema types:", window_types)