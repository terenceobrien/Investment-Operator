"""
Pure-Python rule logic. No LLM calls in this package.

Rules in this package take frozen Pydantic schemas as input and produce
deterministic outputs. They are unit-tested independently of any agent code.

Modules:
- conviction.py  : Combined conviction rules (Phase 1.5)
- constraints.py : Portfolio constraints (Phase 3)
- falsifiers.py  : Falsifier-checking dispatch (Phase 4)
"""

from agent_system.rules.constraints import check_portfolio_constraints
from agent_system.rules.conviction import evaluate_conviction

__all__ = ["check_portfolio_constraints", "evaluate_conviction"]
