from __future__ import annotations
import os
from typing import List, Dict, Any

from openai import OpenAI


class LLMClient:
    """Minimal wrapper around OpenAI responses API for the narrative project.

    The client reads the API key from the OPENAI_API_KEY environment variable
    if one is not provided explicitly.  It exposes a single ``complete`` method
    that returns the raw text output of the model.
    """

    def __init__(self, api_key: str | None = None, timeout: int = 30):
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Missing OPENAI_API_KEY in environment")
        self._client = OpenAI(api_key=key)
        self.timeout = timeout

    def complete(
        self, *, model: str, messages: List[Dict[str, Any]], temperature: float = 0.0
    ) -> str:
        """Send a chat-style request and return the plain-text response.

        ``messages`` should be a list of dicts in the OpenAI chat format.
        """
        resp = self._client.responses.create(
            model=model,
            input=messages,
            temperature=temperature,
            timeout=self.timeout,
        )
        # ``output_text`` is the convenience property that concatenates all
        # generated text pieces into one string.
        return resp.output_text
