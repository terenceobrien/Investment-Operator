"""
Model selection for agent-system LLM calls.

Each agent gets its own model constant so the choice is deliberate and
auditable. Changing a model is a one-line edit in this file. Models
should be chosen based on the agent's task complexity, not defaulted.
"""

# The macro agent does heavy synthesis — regime context + user input +
# 4 few-shot examples + structured output. gpt-5.5 to match the narrative
# pipeline's model choice for consistent quality across the system.
MACRO_AGENT_MODEL = "gpt-5.5"

# The thematic agent does heavy structured synthesis — priority + regime
# context + 3 few-shot examples + ~10 candidates per output with multiple
# fields each. Uses gpt-5.5 to match macro agent for quality consistency.
THEMATIC_AGENT_MODEL = "gpt-5.5"

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
