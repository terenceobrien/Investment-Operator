# package exports for narrative
# Pipeline A (build_narrative_scores) was moved to legacy/ on 2026-04-28.
# The active pipeline is the synthesis pipeline in bundle.py + synth.py.
from .synth import synthesize_narrative_state
from .bundle import build_narrative_bundle

__all__ = ["synthesize_narrative_state", "build_narrative_bundle"]
