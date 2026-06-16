"""LLM-backed structured planning for agent workflows."""

from __future__ import annotations

import json
import os
from typing import Protocol

import requests

from .models import DualKeithleyPlanRequest


DEFAULT_OPENAI_COMPATIBLE_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.5"


class StructuredPlanner(Protocol):
    """Interface for services that turn natural language into typed plans."""

    def plan_dual_keithley(self, goal: str) -> DualKeithleyPlanRequest:
        """Return a structured dual Keithley plan request."""


class OpenAICompatibleStructuredPlanner:
    """Structured planner using an OpenAI-compatible chat completions API.

    The model is constrained to return JSON matching ``DualKeithleyPlanRequest``.
    The caller still performs registry validation and dry-run before execution.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_OPENAI_COMPATIBLE_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_s = timeout_s

    def plan_dual_keithley(self, goal: str) -> DualKeithleyPlanRequest:
        """Return a structured dual Keithley plan request from a user goal."""
        schema = DualKeithleyPlanRequest.model_json_schema()
        response = requests.post(
            self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You plan safe instrument experiments for instr-core. "
                            "Return only structured JSON. Do not emit SCPI commands. "
                            "Use keithley/smu/2600 as the source schema and "
                            "keithley/dmm/dmm6500 as the meter schema unless the "
                            "user explicitly provides another compatible binding."
                        ),
                    },
                    {"role": "user", "content": goal},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "dual_keithley_plan_request",
                        "schema": schema,
                    },
                },
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return DualKeithleyPlanRequest.model_validate(json.loads(content))


def planner_from_env() -> StructuredPlanner | None:
    """Create a structured planner from environment variables if configured."""
    api_key = os.environ.get("INSTR_CORE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAICompatibleStructuredPlanner(
        api_key=api_key,
        model=os.environ.get("INSTR_CORE_LLM_MODEL", DEFAULT_MODEL),
        base_url=os.environ.get("INSTR_CORE_LLM_BASE_URL", DEFAULT_OPENAI_COMPATIBLE_URL),
        timeout_s=float(os.environ.get("INSTR_CORE_LLM_TIMEOUT", "30")),
    )
