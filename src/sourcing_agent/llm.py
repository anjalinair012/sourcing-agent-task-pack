"""Thin wrapper around the Anthropic API: JSON answers, retries, running cost."""

from __future__ import annotations

import json
import os
import threading

import anthropic

SCORER = "claude-haiku-5-5"    # cheap, reads many profiles
THINKER = "claude-sonnet-5-5"  # diagnosis and the recruiter notes
PRICES = {SCORER: (0.10, 0.50), THINKER: (2.00, 10.00)}  # USD per 1M tokens: input, output
MAX_COST = 2.50  # stay under the $3 budget

# An OpenRouter key (sk-or-...) works through the same client, with a different base URL and model names.
OPENROUTER_URL = "https://openrouter.ai/api"
OPENROUTER_IDS = {SCORER: "anthropic/claude-haiku-5.5", THINKER: "anthropic/claude-sonnet-5.5"}


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.startswith("sk-or-"):
        return anthropic.Anthropic(base_url=OPENROUTER_URL, auth_token=key, api_key=None)
    return anthropic.Anthropic()


class LLMError(RuntimeError):
    """An LLM call failed, or the cost cap was reached. Callers treat it as a normal condition."""


class LLM:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or make_client()
        self.openrouter = self.client.base_url.host == "openrouter.ai"
        self.cost = 0.0
        self.calls = 0
        self._lock = threading.Lock()  # scoring runs several calls at once

    def ask_json(self, model: str, system: str, user: str, schema: dict,
                 max_tokens: int = 4000, effort: str = "low") -> dict:
        """Ask for an answer that matches `schema` and return it parsed."""
        if self.cost >= MAX_COST:
            raise LLMError(f"cost cap of ${MAX_COST} reached")
        last = None
        for _ in range(3):
            try:
                r = self.client.messages.create(
                    model=OPENROUTER_IDS[model] if self.openrouter else model,
                    max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": user}],
                    output_config={"effort": effort,
                                   "format": {"type": "json_schema", "schema": schema}},
                )
                price_in, price_out = PRICES[model]
                with self._lock:
                    self.calls += 1
                    self.cost += (r.usage.input_tokens * price_in + r.usage.output_tokens * price_out) / 1e6
                text = next(b.text for b in r.content if b.type == "text")
                return json.loads(text)
            except anthropic.AuthenticationError:
                raise  # a rejected key is not transient: stop the run instead of retrying
            except (anthropic.APIError, json.JSONDecodeError, StopIteration) as e:
                last = e
        raise LLMError(f"LLM call failed 3 times: {last}")
