from __future__ import annotations
import json
import logging
import time
from typing import List, Dict, Any

from .base import BaseScorer, ChunkScore
from ..llm_client import LLMClient


logger = logging.getLogger("narrative.scorers.llm")


class LLMScorer(BaseScorer):
    """Score a text chunk using an LLM.

    The implementation is deterministic (temperature=0) and strictly outputs
    JSON conforming to :class:`ChunkScore`.  If the model's response cannot be
    parsed or fails validation, we retry once with a repair prompt.  After that
    we fall back to a zero score and record error details in metadata.
    """

    def __init__(
        self,
        model: str,
        prompt_version: str = "v1",
        timeout: int = 30,
        max_retries: int = 5,
    ):
        self.model = model
        self.prompt_version = prompt_version
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = LLMClient(timeout=timeout)

    def score(self, text: str) -> ChunkScore:
        base_system = (
            "You are a market narrative analyst. "
            "Do not use price action to infer sentiment."
        )
        # the user message will be populated below with the chunk
        base_user = (
            "Analyze the following text chunk and respond with a JSON object. "
            "The object must have the following integer fields: ``tone`` in [-3..3], "
            "``uncertainty`` in [0..3], and ``themes`` containing integers for "
            "``ai``, ``inflation``, ``liquidity``, ``credit`` and ``consumer`` each "
            "in [-2..2].  If you are unclear, return all zeros." 
            "When scoring tone, it should be scoring the overall direction of macro risk appetite implied by the text. General scoring rubric: +3 indicates strongly risk on/strong growth impulse/easing of economic or financial conditions, "
            "0 = neutral/balanced/informational, -3 = strongly risk off/recessionary signal/tightening of economic or financial conditions."
            "For uncertainty, use this scoring rubric: 0 = clear directional narrative, strong narrative, 3 = conflicting evidence, highly speculative, unclear regime"
            "If the chunk mentions price action, ignore that content when scoring"
            "\n\nTheme scoring – score themes only when the topic is a central part of the text.  If the theme is mentioned only briefly or indirectly, return 0.\n"
            "\n"  # separate paragraphs
            "AI\n"
            "Score how developments in artificial intelligence could influence economic growth, productivity, capital investment, geopolitics, or corporate profitability.\n"
            "Include:\n"
            "•    technological breakthroughs\n"
            "•    corporate AI adoption\n"
            "•    data center / compute infrastructure\n"
            "•    government or military AI programs\n"
            "•    AI regulation\n"
            "Scoring direction:\n"
            "•    +2: developments that increase growth expectations, productivity, or investment\n"
            "•    0: neutral reporting or minor developments\n"
            "•    -2: risks, regulatory barriers, or failures slowing AI adoption\n"
            "\n"
            "Inflation\n"
            "Score information affecting expectations for consumer or producer price inflation.\n"
            "Include:\n"
            "•    CPI/PPI trends\n"
            "•    wage growth\n"
            "•    commodity prices\n"
            "•    supply chain pressures\n"
            "•    inflation expectations\n"
            "•    policy responses to inflation\n"
            "Scoring direction:\n"
            "•    +2: inflation pressures increasing or becoming persistent\n"
            "•    0: neutral updates or mixed signals\n"
            "•    -2: inflation cooling or deflationary forces increasing\n"
            "\n"
            "Liquidity\n"
            "Score factors affecting the availability of capital and financial system liquidity.\n"
            "Include:\n"
            "•    central bank policy\n"
            "•    interest rate expectations\n"
            "•    quantitative easing / tightening\n"
            "•    government fiscal stimulus\n"
            "•    global capital flows\n"
            "•    banking system reserves\n"
            "Scoring direction:\n"
            "•    +2: liquidity expanding or easier financial conditions\n"
            "•    0: neutral / unchanged conditions\n"
            "•    -2: tightening liquidity or restrictive financial conditions\n"
            "\n"
            "Credit\n"
            "Score information about credit conditions and financial system risk.\n"
            "Include:\n"
            "•    credit spreads\n"
            "•    bank lending standards\n"
            "•    corporate default risk\n"
            "•    leveraged finance markets\n"
            "•    banking stress\n"
            "Scoring direction:\n"
            "•    +2: credit conditions improving, risk appetite rising\n"
            "•    0: stable credit environment\n"
            "•    -2: tightening credit, rising defaults, financial stress\n"
            "\n"
            "Consumer\n"
            "Score developments affecting consumer spending and household balance sheets.\n"
            "Include:\n"
            "•    retail sales\n"
            "•    employment and wages\n"
            "•    consumer confidence\n"
            "•    household debt\n"
            "•    savings and consumption trends\n"
            "Scoring direction:\n"
            "•    +2: strong consumer spending outlook\n"
            "•    0: neutral consumer conditions\n"
            "•    -2: weakening consumer demand or financial stress\n"
            "\n"
            "Do not include any other text or explanation; output only the JSON.\n\n"
        )

        def _make_messages(repair: bool = False) -> List[Dict[str, str]]:
            msgs: List[Dict[str, str]] = [
                {"role": "system", "content": base_system},
                {"role": "user", "content": base_user + f"CHUNK:\n{text}"},
            ]
            if repair:
                msgs.append(
                    {
                        "role": "system",
                        "content": (
                            "The previous response was invalid or did not match the "
                            "required schema. Please output *only* valid JSON with the "
                            "fields described earlier."
                        ),
                    }
                )
            return msgs

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            started = time.perf_counter()
            success = False
            try:
                msgs = _make_messages(repair=(attempt > 0))
                raw = self.client.complete(model=self.model, messages=msgs, temperature=0.0)
                data = json.loads(raw)
                score = ChunkScore(**data)
                # add metadata for bookkeeping
                score.metadata = score.metadata or {}
                score.metadata.update({
                    "model": self.model,
                    "prompt_version": self.prompt_version,
                })
                success = True
                return score
            except Exception as exc:  # noqa: BLE001 (catch-all is fine here)
                last_exc = exc
                continue
            finally:
                logger.debug(
                    {
                        "attempt": attempt + 1,
                        "model": self.model,
                        "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                        "success": success,
                    }
                )

        # if we reach here, all attempts failed; return zeroed score
        reason = str(last_exc) if last_exc is not None else "unknown error"
        metadata: Dict[str, Any] = {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "error": reason,
        }
        return ChunkScore(
            tone=0,
            uncertainty=0,
            themes={
                "ai": 0,
                "inflation": 0,
                "liquidity": 0,
                "credit": 0,
                "consumer": 0,
            },
            metadata=metadata,
        )
