from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime, timezone

@dataclass(frozen=True)
class MemoInputs:
    title: str
    ticker: str
    direction: str  # Long / Short
    horizon: str    # days/weeks/months
    conviction: str # Low/Med/High
    position_size: str  # e.g. "2% NAV", "$5k options"
    thesis: str
    key_drivers: List[str]
    risks: List[str]
    invalidation: List[str]
    catalysts: List[str]
    entry_plan: str
    exit_plan: str
    notes: str

def render_memo_markdown(
    m: MemoInputs,
    macro_regime: Optional[Dict[str, str]] = None,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    macro_block = ""
    if macro_regime:
        macro_block = (
            f"**Macro context:** Growth {macro_regime.get('Growth','?')}, "
            f"Inflation {macro_regime.get('Inflation','?')}, "
            f"Liquidity {macro_regime.get('Liquidity','?')}\n"
        )

    def bullets(items: List[str]) -> str:
        items = [x.strip() for x in items if x.strip()]
        return "\n".join([f"- {x}" for x in items]) if items else "- (none)"

    md = f"""# {m.title}

**Ticker:** {m.ticker}  
**Direction:** {m.direction}  
**Horizon:** {m.horizon}  
**Conviction:** {m.conviction}  
**Position size:** {m.position_size}  
**Timestamp:** {ts}  

{macro_block}

## Thesis
{m.thesis.strip() if m.thesis.strip() else "(none)"}

## Key drivers
{bullets(m.key_drivers)}

## Catalysts / events
{bullets(m.catalysts)}

## Risks
{bullets(m.risks)}

## Invalidation / what changes my mind
{bullets(m.invalidation)}

## Entry plan
{m.entry_plan.strip() if m.entry_plan.strip() else "(none)"}

## Exit plan
{m.exit_plan.strip() if m.exit_plan.strip() else "(none)"}

## Notes
{m.notes.strip() if m.notes.strip() else "(none)"}
"""
    return md
