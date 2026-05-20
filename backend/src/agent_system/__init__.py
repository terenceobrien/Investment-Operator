"""
Agent system for Helix research and trade-idea generation.

This module is the structured-output pipeline that sits on top of the existing
Helix infrastructure (regime layers, narrative synthesis, portfolio overlay).
Agents in this system consume and produce frozen Pydantic schemas; the rules
engine is pure Python with no LLM calls.

See README.md for architecture overview.
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "0.1.0"