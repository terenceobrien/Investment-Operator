"""
Extraction runner for the linguistic-signal test.

Reads the transcript manifest, sequences each ticker's calls by REAL call date,
pairs each call with its immediate prior, masks company identity, runs your
FROZEN prompt (loaded from llm_transcript_prompt.md) over the pair at
temperature 0, parses the JSON feature scores, and writes a feature matrix.

Point-in-time discipline enforced here:
  - Each scored call sees ONLY its own prepared remarks and the PRIOR call's
    prepared remarks. Never a future call. Never returns. Never news.
  - No returns data touches this stage at all. Returns are joined in a separate
    later step, so the extraction cannot peek at outcomes.
  - Identity masking reduces (cannot eliminate) the model recalling the real
    company's post-call trajectory from its training data.

Contamination diagnostics baked in:
  - cap_bucket tag per name ('mega' vs 'small_mid'), set in CAP_BUCKET below,
    so you can later compute IC separately per bucket. If the signal only
    shows on mega-caps, it's likely outcome-recall, not real signal.

Model:
  - Pinned to one version via MODEL. DO NOT change mid-run. If you re-run after
    editing the prompt, re-run the WHOLE universe on the same pinned model, or
    score differences become uninterpretable (model drift vs signal).

Usage:
  export ANTHROPIC_API_KEY=...            # or your provider's key
  python3 -m strategy.extract_features            # runs the whole manifest
  python3 -m strategy.extract_features NVDA MU    # limit to specific tickers (test run)

Outputs:
  strategy/features/feature_matrix.csv     # one row per scored (ticker, call)
  strategy/features/evidence/<stem>.json   # per-call full model output for audit
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
MANIFEST = HERE / "transcripts" / "manifest.csv"
PROMPT_FILE = HERE / "llm_transcript_prompt.md"
OUT_DIR = HERE / "features"
EVIDENCE_DIR = OUT_DIR / "evidence"
FEATURE_MATRIX = OUT_DIR / "feature_matrix.csv"

# --- Model config: PIN THIS. Do not change mid-run. -------------------------
# Set to the exact model version you validated against your own hand-reading.
# Check the provider's current model IDs — do not trust a remembered name.
MODEL = "claude-sonnet-5"            # pin this; do not change mid-run
API_URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = 1500
# Note: Sonnet 5 does not accept temperature/top_p/top_k (400 error). Sampling
# params are omitted in call_model; determinism relies on the model default +
# a tightly-specified prompt. If you switch to an older model that DOES accept
# temperature, re-add "temperature": 0.0 to the request for full determinism.

# --- The six pre-registered features (must match your frozen prompt). --------
FEATURES = [
    "hedging_delta",
    "guidance_direction",
    "quant_claim_escalation",
    "new_topic_rate",
    "tone_delta",
    "demand_language_delta",
]

# --- Cap buckets for the contamination split. Edit to match your universe. ---
# 'mega' = heavily-covered names the model likely has outcome memory for.
# 'small_mid' = under-covered names; your PRIMARY test bucket.
CAP_BUCKET = {
    "NVDA": "mega", "AMD": "mega", "AVGO": "mega", "QCOM": "mega", "TXN": "mega",
    "INTC": "mega", "MU": "mega", "AMAT": "mega", "LRCX": "mega", "KLAC": "mega",
    "ADI": "mega", "ASML": "mega", "TSM": "mega", "MRVL": "mega",
    # everything else defaults to small_mid (see bucket_for)
}


# Company names for identity masking. The ticker alone isn't enough — the full
# name ("Analog Devices") is a stronger identity cue than the ticker ("ADI").
# Include the distinctive name tokens you want scrubbed. Masking is defense-in-
# depth only; products/execs still leak identity, which is why the small_mid
# bucket + the famous-vs-obscure IC split are the real contamination controls.
COMPANY_NAMES = {
    "NVDA": "NVIDIA", "AMD": "Advanced Micro Devices", "INTC": "Intel",
    "MU": "Micron", "AVGO": "Broadcom", "QCOM": "Qualcomm",
    "TXN": "Texas Instruments", "ADI": "Analog Devices", "MRVL": "Marvell",
    "MCHP": "Microchip", "NXPI": "NXP", "ON": "onsemi", "SWKS": "Skyworks",
    "QRVO": "Qorvo", "MPWR": "Monolithic Power", "LSCC": "Lattice",
    "AMAT": "Applied Materials", "LRCX": "Lam Research", "KLAC": "KLA",
    "TER": "Teradyne", "ENTG": "Entegris", "ASML": "ASML", "TSM": "Taiwan Semiconductor",
    "STM": "STMicroelectronics", "WOLF": "Wolfspeed", "SLAB": "Silicon Labs",
    "ALGM": "Allegro MicroSystems", "SITM": "SiTime", "AMKR": "Amkor", "UMC": "United Microelectronics",
}


def bucket_for(ticker: str) -> str:
    return CAP_BUCKET.get(ticker, "small_mid")


# ---------------------------------------------------------------------------
# Identity masking
# ---------------------------------------------------------------------------
def mask_identity(text: str, ticker: str, company_name: str | None = None) -> str:
    """
    Reduce obvious identity cues so the model is less able to pattern-match to a
    remembered outcome. This is mitigation, not guarantee — products/execs still
    leak identity, which is exactly why the small_mid bucket matters most.

    Replaces the ticker and (if provided) the company name with 'the Company'.
    Case-insensitive, word-boundary aware.
    """
    masked = text
    if company_name:
        # mask the full name and common truncations (e.g. 'NVIDIA Corporation' -> 'NVIDIA')
        for token in sorted({company_name, company_name.split()[0]}, key=len, reverse=True):
            if len(token) >= 3:
                masked = re.sub(rf"\b{re.escape(token)}\b", "the Company", masked,
                                flags=re.IGNORECASE)
    masked = re.sub(rf"\b{re.escape(ticker)}\b", "the Company", masked, flags=re.IGNORECASE)
    return masked


# ---------------------------------------------------------------------------
# Manifest -> sequenced (prior, current) pairs
# ---------------------------------------------------------------------------
def load_manifest() -> list[dict]:
    with MANIFEST.open() as f:
        return list(csv.DictReader(f))


def build_pairs(rows: list[dict], only: set[str] | None = None) -> list[tuple[dict, dict]]:
    """
    For each ticker, sort its calls by REAL call_date and yield (prior, current)
    consecutive pairs. The FIRST call per ticker has no prior and is skipped
    (it can't be scored on 'change vs prior').
    """
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        if only and r["ticker"] not in only:
            continue
        # skip calls with no reliable prepared-remarks split; handle manually
        if r.get("split_status") not in (None, "", "ok"):
            print(f"  skip {r['ticker']} {r['year']}Q{r['quarter']}: "
                  f"split_status={r.get('split_status')}")
            continue
        by_ticker.setdefault(r["ticker"], []).append(r)

    pairs = []
    for ticker, calls in by_ticker.items():
        calls.sort(key=lambda r: r["call_date"])  # ISO dates sort lexically
        for i in range(1, len(calls)):
            pairs.append((calls[i - 1], calls[i]))
    return pairs


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------
def read_prepared(row: dict) -> str:
    return Path(row["prepared_txt"]).read_text()


def call_model(system_prompt: str, prior_text: str, current_text: str) -> dict:
    """
    Single extraction call. Returns the parsed JSON dict of feature scores.
    Raises on non-200 or unparseable output so failures are loud, not silent.
    """
    user_content = (
        "PRIOR CALL (earlier quarter):\n"
        "<<<PRIOR>>>\n" + prior_text + "\n<<<END PRIOR>>>\n\n"
        "CURRENT CALL (the quarter to score):\n"
        "<<<CURRENT>>>\n" + current_text + "\n<<<END CURRENT>>>\n"
    )
    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            # Sonnet 5 rejects non-default sampling params (temperature/top_p/top_k)
            # with a 400 error, so we omit them. Determinism now comes from the
            # model's default behavior + a tightly-specified prompt, not temp=0.
            # Thinking disabled: this is structured extraction, not reasoning —
            # we want the full token budget going to the JSON output, and
            # adaptive thinking (on by default in Sonnet 5) would eat into it.
            "thinking": {"type": "disabled"},
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    # strip accidental code fences
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\nRaw: {text[:400]}")


def extract_scores(parsed: dict) -> dict:
    """Pull the six integer scores out of the model's JSON, validating shape."""
    out = {}
    for feat in FEATURES:
        node = parsed.get(feat)
        if isinstance(node, dict) and "score" in node:
            out[feat] = int(node["score"])
        elif isinstance(node, (int, float)):
            out[feat] = int(node)
        else:
            raise ValueError(f"missing/invalid feature '{feat}' in model output")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if "ANTHROPIC_API_KEY" not in os.environ:
        raise SystemExit("Set ANTHROPIC_API_KEY.")
    if not PROMPT_FILE.exists():
        raise SystemExit(f"Frozen prompt not found at {PROMPT_FILE}")
    system_prompt = PROMPT_FILE.read_text()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    only = set(sys.argv[1:]) or None
    rows = load_manifest()
    pairs = build_pairs(rows, only)
    print(f"Model: {MODEL}  |  {len(pairs)} (prior,current) pairs to score"
          f"{' [filtered: ' + ','.join(only) + ']' if only else ''}\n")

    results = []
    for prior, current in pairs:
        stem = f"{current['ticker']}_{current['year']}Q{current['quarter']}"
        try:
            prior_txt = mask_identity(read_prepared(prior), prior["ticker"],
                                      COMPANY_NAMES.get(prior["ticker"]))
            curr_txt = mask_identity(read_prepared(current), current["ticker"],
                                     COMPANY_NAMES.get(current["ticker"]))
            parsed = call_model(system_prompt, prior_txt, curr_txt)
            scores = extract_scores(parsed)

            # save full model output (scores + evidence) for hand-auditing
            (EVIDENCE_DIR / f"{stem}.json").write_text(json.dumps(parsed, indent=2))

            row = {
                "ticker": current["ticker"],
                "cap_bucket": bucket_for(current["ticker"]),
                "call_date": current["call_date"],
                "earnings_timing": current["earnings_timing"],
                "prior_date": prior["call_date"],
                "year": current["year"],
                "quarter": current["quarter"],
                **scores,
                "composite": sum(scores.values()),  # simple equal-weight sum for a first look
            }
            results.append(row)
            print(f"  + {stem}: " + " ".join(f"{k}={scores[k]:+d}" for k in FEATURES)
                  + f"  [comp {row['composite']:+d}]")
        except Exception as e:
            print(f"  ! {stem}: {e}")
        time.sleep(0.5)  # gentle pacing

    if not results:
        raise SystemExit("No results produced.")

    fieldnames = ["ticker", "cap_bucket", "call_date", "earnings_timing",
                  "prior_date", "year", "quarter", *FEATURES, "composite"]
    with FEATURE_MATRIX.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    print(f"\nWrote {len(results)} rows -> {FEATURE_MATRIX}")
    print(f"Per-call evidence -> {EVIDENCE_DIR}/  (hand-audit these against the transcripts)")


if __name__ == "__main__":
    main()