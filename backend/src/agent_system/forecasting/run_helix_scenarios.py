"""
Run all Helix scenarios through FRB/US and write a handoff for the Helix
macro forecast.

Usage (from the pyfrbus repo, with this file in scenarios/helix/):

    python scenarios/helix/run_helix_scenarios.py \
        --start-quarter 2026Q3 \
        --horizon 12 \
        --map scenarios/helix/helix_scenario_map.yaml

Outputs (to data/agent_system/frbus_handoffs/ by default):
    frbus_scenario_paths_<start>_<timestamp>.json   — the Helix handoff
    <scenario_id>_<start>.csv                       — per-scenario key series
    frbus_scenarios_<start>.png                     — overlay chart, all scenarios

The JSON handoff is the integration artifact: Helix reads it to attach
quantitative macro paths to each narrative scenario (analogue matching,
falsifier thresholds). It does NOT feed the probability engine.

Fail-loud: unknown template names, bad params, missing data columns, and
scenario solve failures all abort the run with a clear message. No partial
handoff is written on failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from math import ceil

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(1, BACKEND_ROOT)

from src.agent_system.paths import fed_model_dir, frbus_handoffs_dir  # noqa: E402

FED_MODEL_DIR = str(fed_model_dir(create=False))
sys.path.insert(0, FED_MODEL_DIR)

from shock_templates import TEMPLATES, TemplateError  # noqa: E402

from pyfrbus.frbus import Frbus  # noqa: E402
from pyfrbus.load_data import load_data  # noqa: E402


# ─── key series extracted for the handoff ───────────────────────────────

def extract_paths(df: pd.DataFrame, start: pd.Period, end: pd.Period) -> dict[str, list[float]]:
    """Pull the key macro series over [start, end] as plain lists."""
    window = pd.period_range(start, end, freq="Q")

    def series(s: pd.Series) -> list[float]:
        return [round(float(v), 4) if pd.notna(v) else None for v in s[window]]

    return {
        "xgdp_growth_4q_pct": series(df["xgdp"].pct_change(4) * 100),
        "xgdp_level": series(df["xgdp"]),
        "lur_pct": series(df["lur"]),
        "core_pce_inflation_4q_pct": series(df["pcxfe"].pct_change(4) * 100),
        "rff_pct": series(df["rff"]),
        "rg10_pct": series(df["rg10"]),
        "ebfi_level": series(df["ebfi"]),
        "rbbbp_pct": series(df["rbbbp"]),
    }


def deltas(scenario: dict[str, list], base: dict[str, list]) -> dict[str, list]:
    out: dict[str, list] = {}
    for key in scenario:
        out[key] = [
            round(s - b, 4) if (s is not None and b is not None) else None
            for s, b in zip(scenario[key], base[key])
        ]
    return out


def file_fingerprint(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def default_outdir() -> str:
    return str(frbus_handoffs_dir(create=False))


# ─── main ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-quarter", required=True, help="e.g. 2026Q3")
    parser.add_argument("--horizon", type=int, default=12, help="quarters (default 12)")
    parser.add_argument("--map", default=os.path.join(HERE, "helix_scenario_map.yaml"))
    parser.add_argument("--data", default=os.path.join(FED_MODEL_DIR, "data", "LONGBASE.TXT"))
    parser.add_argument("--model", default=os.path.join(FED_MODEL_DIR, "models", "model.xml"))
    parser.add_argument("--outdir", default=default_outdir())
    parser.add_argument("--no-chart", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    start = pd.Period(args.start_quarter, freq="Q")
    end = start + args.horizon - 1

    with open(args.map) as f:
        mapping = yaml.safe_load(f)
    scenario_specs: dict = mapping.get("scenarios", {})
    if not scenario_specs:
        print(f"FATAL: no scenarios in {args.map}", file=sys.stderr)
        return 1

    # Validate all templates BEFORE the (slow) model load
    for sid, spec in scenario_specs.items():
        tname = spec.get("template")
        if tname not in TEMPLATES:
            print(
                f"FATAL: scenario '{sid}' references unknown template '{tname}'. "
                f"Available: {sorted(TEMPLATES)}",
                file=sys.stderr,
            )
            return 1

    print(f"Loading data: {args.data}")
    data = load_data(args.data)
    print(f"Loading model: {args.model}")
    frbus = Frbus(args.model)

    # Standard policy configuration (matches the Fed demos and
    # recession_2026.py): surplus-ratio fiscal targeting, and the funds
    # rate follows the model's default rule as configured in LONGBASE
    # (inertial Taylor via the dmp* switches).
    data.loc[start:end, "dfpdbt"] = 0
    data.loc[start:end, "dfpsrp"] = 1

    print(f"Computing tracking-residual baseline over {start}..{end}")
    with_adds = frbus.init_trac(start, end, data)

    baseline_sim = TEMPLATES["baseline"](frbus, with_adds, start, end)
    base_paths = extract_paths(baseline_sim, start, end)

    results: dict[str, dict] = {}
    sims: dict[str, pd.DataFrame] = {"baseline": baseline_sim}

    for sid, spec in scenario_specs.items():
        tname = spec["template"]
        params = spec.get("params", {}) or {}
        print(f"Running {sid}  [{tname}]  params={params}")
        try:
            sim = TEMPLATES[tname](frbus, with_adds, start, end, **params)
        except TemplateError as exc:
            print(f"FATAL: scenario '{sid}' failed: {exc}", file=sys.stderr)
            return 1
        except TypeError as exc:
            print(
                f"FATAL: scenario '{sid}' has params not accepted by template "
                f"'{tname}': {exc}",
                file=sys.stderr,
            )
            return 1

        paths = extract_paths(sim, start, end)
        results[sid] = {
            "template": tname,
            "params": params,
            "rationale": (spec.get("rationale") or "").strip(),
            "paths": paths,
            "deltas_vs_baseline": deltas(paths, base_paths),
        }
        sims[sid] = sim

        csv_path = os.path.join(args.outdir, f"{sid}_{start}.csv")
        out = pd.DataFrame(index=pd.period_range(start, end, freq="Q"))
        for var in ["xgdp", "lur", "pcxfe", "rff", "rg10", "ebfi", "rbbbp"]:
            out[f"{var}_base"] = baseline_sim.loc[start:end, var]
            out[f"{var}_scen"] = sim.loc[start:end, var]
        out.to_csv(csv_path)

    # ─── handoff JSON ────────────────────────────────────────────────────
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    handoff = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "map_version": (mapping.get("meta") or {}).get("map_version", "unversioned"),
        "baseline_data_file": os.path.abspath(args.data),
        "baseline_data_fingerprint": file_fingerprint(args.data),
        "model_file": os.path.abspath(args.model),
        "start_quarter": str(start),
        "horizon_quarters": args.horizon,
        "quarters": [str(p) for p in pd.period_range(start, end, freq="Q")],
        "baseline_paths": base_paths,
        "scenarios": results,
    }
    handoff_path = os.path.join(
        args.outdir, f"frbus_scenario_paths_{start}_{timestamp}.json"
    )
    with open(handoff_path, "w") as f:
        json.dump(handoff, f, indent=2)
    print(f"\nHandoff written: {handoff_path}")

    # ─── overlay chart ───────────────────────────────────────────────────
    if not args.no_chart:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        panels = {
            "Real GDP growth (4-qtr %)": "xgdp_growth_4q_pct",
            "Unemployment rate": "lur_pct",
            "Core PCE inflation (4-qtr %)": "core_pce_inflation_4q_pct",
            "Federal funds rate": "rff_pct",
            "IG yield": "rbbbp_pct"
        }
        quarters = handoff["quarters"]
        fig, axes = plt.subplots(2, 2, figsize=(12, 9))
        for ax, (title, key) in zip(axes.flat, panels.items()):
            ax.plot(range(len(quarters)), base_paths[key], color="black", lw=2, label="baseline")
            for sid, res in results.items():
                ax.plot(range(len(quarters)), res["paths"][key], ls="--", lw=1.4, label=sid)
            xt = range(0, len(quarters), ceil(len(quarters) / 5))
            ax.set_xticks(list(xt))
            ax.set_xticklabels([quarters[i] for i in xt], fontsize=8)
            ax.set_title(title, fontsize=11)
            ax.grid(alpha=0.25)
        axes[0, 0].legend(fontsize=7)
        fig.suptitle(f"FRB/US scenario paths — {start}, horizon {args.horizon}q", fontsize=13)
        fig.tight_layout()
        chart_path = os.path.join(args.outdir, f"frbus_scenarios_{start}.png")
        fig.savefig(chart_path, dpi=150)
        print(f"Chart written:   {chart_path}")

    print("\nSummary (peak deltas vs baseline over horizon):")
    for sid, res in results.items():
        d = res["deltas_vs_baseline"]
        gdp = [v for v in d["xgdp_growth_4q_pct"] if v is not None]
        lur = [v for v in d["lur_pct"] if v is not None]
        rff = [v for v in d["rff_pct"] if v is not None]
        rbbbp = [v for v in d["rbbbp_pct"] if v is not None]
        print(
            f"  {sid:<32} GDP4q {min(gdp):+.2f}/{max(gdp):+.2f}pp   "
            f"LUR {min(lur):+.2f}/{max(lur):+.2f}pp   "
            f"RFF {min(rff):+.2f}/{max(rff):+.2f}pp   "
            f"IGY {min(rbbbp):+.2f}/{max(rbbbp):+.2f}pp"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
