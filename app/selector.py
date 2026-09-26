import json
from abc import ABC, abstractmethod
from typing import Any

from app.config import Config
from app.schemas import SelectionResult


class Selector(ABC):
    """Picks one option id from a host-prepared list, or abstains.

    The selector never sees more than the option ids and context the host
    hands it, and its return value is only ever a candidate id or an
    abstention — never a free-form instruction.
    """

    @abstractmethod
    def select(self, options: list[str], context: dict[str, Any]) -> SelectionResult: ...


class FakeSelector(Selector):
    """Deterministic selector for tests: always returns a fixed choice."""

    def __init__(self, choice_id: str | None = None, abstain: bool = False):
        self._choice_id = choice_id
        self._abstain = abstain

    def select(self, options: list[str], context: dict[str, Any]) -> SelectionResult:
        if self._abstain:
            return SelectionResult(choice_id=None, abstained=True)
        return SelectionResult(choice_id=self._choice_id, abstained=False)


class GeminiSelector(Selector):
    """Selector backed by Gemini via Vertex AI, constrained to structured output."""

    _ABSTAIN_SENTINEL = "__ABSTAIN__"

    # Standard-tier list price per Google's Gemini API pricing page
    # (https://ai.google.dev/gemini-api/docs/pricing), text/image/video input.
    # Only the model this service is actually configured to run as a selector
    # needs an entry -- an unpriced model just means cost is left unreported.
    _PRICE_PER_MILLION_TOKENS_USD = {
        "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    }

    def __init__(self, config: Config):
        from google import genai

        self._model = config.gemini_model
        self._client = genai.Client(
            vertexai=True,
            project=config.gcp_project,
            location=config.gcp_location,
        )

    def select(self, options: list[str], context: dict[str, Any]) -> SelectionResult:
        from google.genai import types

        if not options:
            return SelectionResult(choice_id=None, abstained=True)

        prompt = (
            "Choose exactly one option id below, or abstain if none clearly fit. "
            "Never invent an id that is not listed.\n\n"
            f"options: {json.dumps(options)}\n"
            f"context: {json.dumps(context, default=str)}\n"
        )

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # A plain enum response (single token out) is enough for a
                # pick-one-or-abstain choice -- no need to pay for full JSON
                # object generation/decoding. See
                # https://ai.google.dev/gemini-api/docs/structured-output
                response_mime_type="text/x.enum",
                response_schema={"type": "STRING", "enum": [*options, self._ABSTAIN_SENTINEL]},
                # This is a bounded choice, not open-ended reasoning: extended
                # thinking and a large output budget only add latency here,
                # so both are pinned to the minimum.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                max_output_tokens=16,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        choice = (response.text or "").strip()
        abstain = choice == self._ABSTAIN_SENTINEL or choice not in options
        choice_id = choice if not abstain else None
        return SelectionResult(
            choice_id=choice_id,
            abstained=abstain,
            raw={"choice": choice, "cost_usd": self._cost_usd(response.usage_metadata)},
        )

    def _cost_usd(self, usage: Any) -> float | None:
        prices = self._PRICE_PER_MILLION_TOKENS_USD.get(self._model)
        if usage is None or prices is None:
            return None
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
