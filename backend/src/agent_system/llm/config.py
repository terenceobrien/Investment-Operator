"""
Model selection for agent-system LLM calls.

Each agent gets its own model constant so the choice is deliberate and
auditable. Changing a model is a one-line edit in this file. Models
should be chosen based on the agent's task complexity, not defaulted.
"""

import os

# The macro agent does heavy synthesis — regime context + user input +
# 4 few-shot examples + structured output. gpt-5.5 to match the narrative
# pipeline's model choice for consistent quality across the system.
MACRO_AGENT_MODEL = "gpt-5.5"

# The thematic agent does heavy structured synthesis — priority + regime
# context + 3 few-shot examples + ~10 candidates per output with multiple
# fields each. Uses gpt-5.5 to match macro agent for quality consistency.
THEMATIC_AGENT_MODEL = "gpt-5.5"

# The deep fundamental agent synthesizes company, financial, macro/theme,
# screen, and variant-view context. Default to the thematic model but allow
# operational override without code changes.
DEEP_FUNDAMENTAL_AGENT_MODEL = os.getenv(
    "DEEP_FUNDAMENTAL_AGENT_MODEL",
    THEMATIC_AGENT_MODEL,
)

# The company profile agent builds business-model context for arbitrary
# tickers. Use the same default as deep fundamental synthesis, with an
# operational override for cost/latency experiments.
COMPANY_PROFILE_AGENT_MODEL = os.getenv(
    "COMPANY_PROFILE_AGENT_MODEL",
    DEEP_FUNDAMENTAL_AGENT_MODEL,
)

# The evidence extraction agent reads source documents and extracts concise,
# source-backed evidence. Default to the deep fundamental model, with an
# override for cost/latency tuning.
EVIDENCE_EXTRACTION_AGENT_MODEL = os.getenv(
    "EVIDENCE_EXTRACTION_AGENT_MODEL",
    DEEP_FUNDAMENTAL_AGENT_MODEL,
)

# The trade expression agent converts accepted candidates into concrete
# expressions with sizing, falsifiers, and review cadence. It needs the same
# structured-reasoning quality as the macro/thematic agents but a smaller
# context window.
TRADE_EXPRESSION_AGENT_MODEL = "gpt-5.5"

# Scenario generation and trade-against-scenario scoring are explicit refresh
# workflows with structured macro synthesis. Use the same reasoning model as
# the other synthesis-heavy agents.
SCENARIO_AGENT_MODEL = "gpt-5.5"

# Future agents will live here as they're built.
# FUNDAMENTAL_AGENT_MODEL = ...
# NARRATIVE_AGENT_MODEL = ...
