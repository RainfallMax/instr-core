"""Canonical dry-run validation context fingerprints."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def validation_context_fingerprint(payload: dict[str, Any]) -> str:
    """Return SHA-256 for deterministic compact JSON."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_validation_context(
    run: Any,
    registry: Any,
    sessions: Any,
    states: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build canonical context for a single or dual instrument run."""
    plan = run.plan
    if hasattr(plan, "source") and hasattr(plan, "meter"):
        bindings = [plan.source, plan.meter]
    else:
        bindings = [
            type(
                "Binding",
                (),
                {
                    "address": plan.address,
                    "instrument_key": plan.instrument_key,
                },
            )()
        ]

    schema_payload: dict[str, Any] = {}
    instrument_payload: dict[str, Any] = {}
    state_payload: dict[str, Any] = {}
    for binding in bindings:
        schema = registry.get_schema(binding.instrument_key)
        schema_payload[binding.instrument_key] = schema.model_dump(mode="json")
        try:
            session = sessions.get(binding.address)
        except LookupError:
            instrument_payload[binding.address] = {
                "idn": None,
                "schema_key": None,
                "healthy": False,
            }
        else:
            instrument_payload[binding.address] = {
                "idn": session.instrument.idn,
                "schema_key": session.instrument.schema_key,
                "healthy": session.healthy,
            }
        state_payload[binding.address] = states.get(binding.address, {})

    return {
        "plan": plan.model_dump(mode="json"),
        "schemas": schema_payload,
        "instruments": instrument_payload,
        "states": state_payload,
    }
