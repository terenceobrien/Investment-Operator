agent_system
Structured research and trade-idea generation pipeline for Helix Intel.
This module sits on top of the existing Helix infrastructure (regime layers,
narrative synthesis, portfolio overlay) and produces structured, auditable
trade ideas — or, more often, logged rejections explaining why an idea didn't
clear the conviction bar.
Design principles

Schemas and rules are the contract. Agents are interchangeable; the
structured outputs they produce and consume are not. If you find yourself
rewriting schemas to fit a new prompt, stop — fix the prompt instead.
Pragmatic to a fault. The system is designed to produce zero trade
ideas on most days. A pass decision is a normal, expected output, not
a failure. Every rejection is logged with full reasoning so the calibration
of "exceptional or pass" can be reviewed and tuned over time.
No hallucinated confidence. Every claim requires evidence with a
traceable source. Every rating requires a named rule. Every trade requires
falsifiers. Construction is forced to enumerate "what would the bear case
be" and "what would I see first if this is going wrong" before producing
an idea.
Code-based conviction rules. Conviction rules live in pure Python
(rules/conviction.py), not in prompts. They're unit-tested. Changing
a rule requires editing code and updating tests, not tweaking a prompt.

Module layout
backend/src/agent_system/
├── schemas/         # Pydantic models — the contract layer
│   ├── common.py    # Evidence, Falsifier, Catalyst, Conviction, enums
│   ├── regime.py    # RegimeState, ResearchPriority           (Phase 1.3)
│   ├── thematic.py  # ThematicMap, Candidate                  (Phase 1.3)
│   ├── fundamental.py  # FundamentalAnalysis                  (Phase 1.3)
│   ├── narrative.py    # NarrativeAnalysis                    (Phase 1.3)
│   ├── trade.py        # TradeIdea, TradeExpression           (Phase 1.3)
│   └── portfolio.py    # PortfolioState, ActiveThesis, etc.   (Phase 1.3)
├── rules/           # Pure-Python rule logic, no LLM calls
│   ├── conviction.py    # Combined conviction rules           (Phase 1.5)
│   ├── constraints.py   # Portfolio constraints               (Phase 3)
│   └── falsifiers.py    # Falsifier-checking logic            (Phase 4)
├── storage/         # Database layer
│   ├── models.py        # SQLAlchemy ORM models               (Phase 1.4)
│   ├── migrations/      # Alembic                             (Phase 1.4)
│   └── repository.py    # Schemas in, schemas out             (Phase 1.4)
└── tests/
    ├── test_schemas_common.py   # ✓ Phase 1.2 — done
    └── fixtures/                # Hand-crafted JSON examples
Schema conventions
All schemas inherit from BaseSchema, which enforces:

Frozen. Mutation raises ValidationError. Use model_copy(update={...})
to derive a modified version. This protects the rules engine from objects
changing underneath it.
Strict. Extra fields raise ValidationError. This catches LLM typos
immediately — a misspelled field name will fail at validation, not silently
drop data.
Versioned. Every schema instance carries schema_version and
created_at. The version field is the basis for future migrations.

Evidence
Evidence is a discriminated union by source_type. The variants:

FREDEvidence — FRED data series (requires series_id, observation_date)
NewsEvidence — published web content (requires publisher, title)
FilingEvidence — regulatory filings (requires cik, accession_number)
PriceEvidence — price/technical data (requires ticker, metric)
PositioningEvidence — positioning/flow/sentiment (requires instrument, metric)
DerivedEvidence — computed from other evidence (requires upstream_claims)

If an agent emits evidence with source_type: "fred" but no series_id,
validation fails. This is deliberate — "evidence with no link" is the most
common failure mode of LLM research output.
Inefficiency archetypes
The InefficiencyArchetype enum is built dynamically from
inefficiency_taxonomy.INEFFICIENCY_TAXONOMY at import time. Adding a new
archetype to the taxonomy makes it available here automatically. The enum
always includes an UNKNOWN sentinel for unclassifiable cases.
Use archetype_from_taxonomy_id(value) to convert a taxonomy id, name, or
alias to the enum member. Returns UNKNOWN for unrecognized input.
Running the tests
From the project root:

```bash
pytest backend/src/agent_system/tests/ -v
```

From inside `backend/`:

```bash
pytest src/agent_system/tests/ -v
```

All schema tests should pass. They double as living documentation — if you're
unsure how to construct a particular type, find the test that exercises it.

Running the stub research cycle

From inside `backend/`:

```bash
python -m src.agent_system.orchestration.run_research_cycle
```

The stub cycle is deterministic and fully local. It calls no LLMs, no live
market-data APIs, no web search, and no brokerage/execution services. Its
purpose is to validate the execution spine from RegimeState to ResearchPriority
to ThematicMap to candidate research, conviction rules, TradeIdea construction,
portfolio constraint checks, and decision logging.

Accepted and rejected ideas are both expected. The default scenario is
"supply-shock inflation / late-cycle tightening with resilient AI earnings."
ETN is designed to clear the rules as an accepted idea; crowded or weakly
differentiated candidates such as NVDA, SMH, VST, IFRA, and PAVE are logged as
rejections. Those rejections are first-class calibration data, not failures.

New v0 execution modules:

- `storage/models.py` and `storage/repository.py`: append-only JSONL storage
  under `data/agent_system/` by default. Set `AGENT_SYSTEM_DATA_DIR` to redirect
  storage during tests or local experiments.
- `rules/conviction.py`: deterministic, conservative multi-layer conviction
  rules. Hard-pass rules fire before constructive ratings.
- `rules/constraints.py`: simple portfolio constraint checks that distinguish
  hard blocks from adjustable constraints.
- `orchestration/stub_agents.py`: schema-valid fake agents for the current
  macro/theme scenario.
- `orchestration/run_research_cycle.py`: CLI runner that saves schema records
  and appends decision log entries.

Storage files written by the runner:

- `data/agent_system/schema_records.jsonl`
- `data/agent_system/decision_log.jsonl`

Internal review page

After generating local stub output:

```bash
cd backend
python -m src.agent_system.orchestration.run_research_cycle
```

start the backend/frontend and visit:

```text
/agent-system
```

The page is internal/dev-facing. It reads local JSONL outputs through protected
backend endpoints, shows the latest cycle summary, accepted ideas, rejected
ideas, decision log entries, and a raw audit trail for selected trades. No live
APIs, LLMs, brokerages, or execution calls are introduced.

The optional run button calls `POST /api/agent-system/run-stub-cycle`, which is
disabled unless the backend has:

```bash
ENABLE_AGENT_SYSTEM_DEV_ENDPOINTS=true
AGENT_SYSTEM_DATA_DIR=/absolute/path/to/project/data/agent_system
```

Rejected ideas are expected and valuable; they are displayed alongside accepted
ideas for calibration.
Adding a new schema

Add the model to the appropriate file in schemas/
Re-export it from schemas/__init__.py
Add corresponding tests in tests/
If the schema introduces a new enum or shared type, add it to common.py
so other schemas can import it without circular dependencies.

Phase 1 status

 1.1 Module scaffold
 1.2 Foundational schemas (common.py)
 1.3 Domain schemas (regime.py → portfolio.py)
 1.4 Storage layer (ORM + repository)
 1.5 Conviction rules engine
 1.6 Test fixtures and manual verification
 1.7 Decision log (decisions.md)
