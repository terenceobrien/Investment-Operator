import numpy as np, glob, json

# absolute search so cwd doesn't matter
hits = glob.glob("/Users/terenceobrien/AI_Financial_Operator/**/garch_*.npz", recursive=True)
if not hits:
    raise SystemExit("No garch_*.npz found anywhere under AI_Financial_Operator")
path = sorted(hits)[-1]
print("artifact:", path)

a = np.load(path, allow_pickle=True)
m = json.loads(str(a["metadata_json"]))
q = [str(x) for x in m["residual_quarters"]]
vo = [str(x) for x in m["variable_order"]]
print("n quarters:", len(q), "| range:", q[0], "..", q[-1])
print("variables:", vo)

cv = np.asarray(a["conditional_volatility"], dtype=float)
print("cond_vol shape:", cv.shape)
ci = vo.index("credit_spread")

print("\ncredit_spread conditional vol:")
for t in ["2007Q4","2008Q1","2008Q3","2008Q4","2009Q1","2020Q1","2020Q2","2026Q1"]:
    print(" ", t, round(float(cv[q.index(t)][ci]),4) if t in q else "NOT in series")

print("\nseries min/mean/max:",
      round(float(cv[:,ci].min()),4),
      round(float(cv[:,ci].mean()),4),
      round(float(cv[:,ci].max()),4))