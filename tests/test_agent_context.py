"""Tests for dry-run validation context fingerprints."""

from __future__ import annotations

from instr_core.agent.context import validation_context_fingerprint


def test_fingerprint_is_deterministic_and_order_independent() -> None:
    first = {
        "plan": {"b": 2, "a": 1},
        "states": {"USB0::2": {}, "USB0::1": {"output": "OFF"}},
    }
    second = {
        "states": {"USB0::1": {"output": "OFF"}, "USB0::2": {}},
        "plan": {"a": 1, "b": 2},
    }

    assert validation_context_fingerprint(first) == validation_context_fingerprint(second)


def test_fingerprint_changes_with_plan_schema_identity_or_state() -> None:
    base = {
        "plan": {"stop": 1},
        "schemas": {"smu": {"max": 40}},
        "instruments": {"USB0::1": {"idn": "K,2600", "healthy": True}},
        "states": {"USB0::1": {"output": "OFF"}},
    }

    variants = [
        base | {"plan": {"stop": 2}},
        base | {"schemas": {"smu": {"max": 20}}},
        base | {"instruments": {"USB0::1": {"idn": "K,2601", "healthy": True}}},
        base | {"states": {"USB0::1": {"output": "ON"}}},
    ]

    original = validation_context_fingerprint(base)
    assert all(validation_context_fingerprint(item) != original for item in variants)
