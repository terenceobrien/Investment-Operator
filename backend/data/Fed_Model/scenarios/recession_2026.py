"""
Recession scenario, conditional forecast starting 2026Q3.

Scenario: a demand-driven downturn hits in 2026Q3. Real GDP growth is forced
to [-1.0, -1.5, -0.5, +0.5] percent (annualized) over the first four quarters
via mcontrol; after that the trajectory is released (NaN) and the model's own
dynamics take over. Monetary policy responds through the model's standard
inertial Taylor rule; fiscal policy uses surplus-ratio targeting.

Outputs (written to scenarios/output/):
  recession_2026.png  - 4-panel baseline-vs-scenario chart
  recession_2026.csv  - key series, baseline and scenario
Also opens the interactive plot window when run from a terminal.
"""

import os
from math import ceil

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from pyfrbus.frbus import Frbus
from pyfrbus.load_data import load_data

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "output")
os.makedirs(OUTDIR, exist_ok=True)

# ---------------------------------------------------------------- setup
data = load_data(os.path.join(HERE, "..", "data", "LONGBASE.TXT"))
frbus = Frbus(os.path.join(HERE, "..", "models", "model.xml"))

start = pd.Period("2026Q3")
end = start + 11  # 3-year horizon

# Standard policy configuration (same as the Fed's demos):
# fiscal surplus-ratio targeting, inertial Taylor rule for the funds rate
data.loc[start:end, "dfpdbt"] = 0
data.loc[start:end, "dfpsrp"] = 1

# Baseline with tracking residuals: model reproduces LONGBASE exactly
with_adds = frbus.init_trac(start, end, data)

# ------------------------------------------------------- scenario design
# Force annualized real GDP growth for the first 4 quarters, then release
growth_annualized = [-1.0, -1.5, -0.5, 0.5]
shock_end = start + len(growth_annualized) - 1

gdp_path = with_adds.loc[start - 1, "xgdp"] * np.cumprod(
    (1 + np.array(growth_annualized) / 100) ** 0.25
)
with_adds.loc[start:end, "xgdp_t"] = np.nan  # NaN = target inactive
with_adds.loc[start:shock_end, "xgdp_t"] = gdp_path

# Target GDP using a consumption shock as the instrument;
# everything else (unemployment, inflation, rates) responds endogenously
sim = frbus.mcontrol(
    start, end, with_adds,
    targ=["xgdp"], traj=["xgdp_t"], inst=["eco_aerr"],
)

# ------------------------------------------------------------- outputs
key = {
    "Real GDP growth (4-qtr %)": lambda d: d["xgdp"].pct_change(4) * 100,
    "Unemployment rate": lambda d: d["lur"],
    "Core PCE inflation (4-qtr %)": lambda d: d["pcxfe"].pct_change(4) * 100,
    "Federal funds rate": lambda d: d["rff"],
}

periods = pd.period_range(start - 4, end, freq="Q")
fig, axes = plt.subplots(2, 2, figsize=(10, 8))
for ax, (title, f) in zip(axes.flat, key.items()):
    ax.plot(range(len(periods)), f(with_adds)[periods], label="Baseline")
    ax.plot(range(len(periods)), f(sim)[periods], ls="--", label="Recession scenario")
    xt = range(0, len(periods), ceil(len(periods) / 4))
    ax.set_xticks(xt)
    ax.set_xticklabels([str(periods[i]) for i in xt])
    ax.set_title(title)
axes[0, 0].legend()
fig.tight_layout()
fig.savefig(os.path.join(OUTDIR, "recession_2026.png"), dpi=150)

out = pd.DataFrame(index=pd.period_range(start, end, freq="Q"))
for name, series in [("base", with_adds), ("scen", sim)]:
    for var in ["xgdp", "lur", "pcxfe", "rff", "rg10"]:
        out[f"{var}_{name}"] = series.loc[start:end, var]
out.to_csv(os.path.join(OUTDIR, "recession_2026.csv"))

print("Saved:", os.path.join(OUTDIR, "recession_2026.png"))
print("Saved:", os.path.join(OUTDIR, "recession_2026.csv"))
print(out[["lur_base", "lur_scen", "rff_base", "rff_scen"]].round(2).head(8))

plt.show()
