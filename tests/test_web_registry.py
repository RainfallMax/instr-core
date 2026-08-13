"""Runtime registry compatibility for web-exported SMU contracts.

The SQL/JSON fixture gate (``test_web_contracts.py``) proves the web contract
*shapes* load as ``InstrumentSchema``.  This module proves the stronger claim
that matters for instrument control: the same contracts load through the
*runtime* ``Registry`` path the MCP server actually uses, and the ``validate_command``
firewall rejects unsafe values against those runtime-loaded contracts.

The YAML files live under ``fixtures/registry/web/`` and are synced from
``instr.web`` by ``scripts/verify-web-contracts.py`` (``pnpm registry:export``).
"""

from __future__ import annotations

from pathlib import Path

from instr_core.validator import Registry, validate_command


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "web_registry"

EXPECTED_MODELS = (
    "2601b",
    "2602b",
    "2604b",
    "2611b",
    "2612b",
    "2614b",
    "2634b",
    "2635b",
    "2636b",
)


def test_web_registry_loads_all_nine_smu_models() -> None:
    registry = Registry.load(FIXTURES_ROOT)

    keys = registry.list_instruments()
    assert len(keys) == 9
    for model in EXPECTED_MODELS:
        assert f"keithley/smu/{model}" in keys


def test_web_registry_rejects_out_of_range_voltage_at_runtime() -> None:
    registry = Registry.load(FIXTURES_ROOT)
    schema = registry.get_schema("keithley/smu/2611b")

    assert schema.global_limits.voltage is not None
    assert schema.global_limits.voltage.max == 202

    # In-range state but out-of-range value must be rejected.
    result = validate_command(schema, ":SOUR:VOLT", "999", {"source_mode": "VOLT"})

    assert result.valid is False
    assert any(
        "out of range" in issue.lower() or "voltage max" in issue.lower()
        for issue in result.issues
    )


def test_web_registry_enforces_compliance_before_source() -> None:
    registry = Registry.load(FIXTURES_ROOT)
    schema = registry.get_schema("keithley/smu/2611b")

    # Value is in range, but compliance (:SENS:CURR:PROT) was never set.
    result = validate_command(schema, ":SOUR:VOLT", "100", {"source_mode": "VOLT"})

    assert result.valid is False
    assert any("compliance" in issue.lower() for issue in result.issues)
