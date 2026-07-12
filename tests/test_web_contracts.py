"""Compatibility checks for contracts exported by instr.web."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from instr_core.schema import CommandDef, InstrumentSchema
from instr_core.validator import validate_command


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "web_contracts"


def _contract_paths() -> list[Path]:
    return sorted(FIXTURES_ROOT.glob("*.json"))


def _load_web_contract(path: Path) -> InstrumentSchema:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return InstrumentSchema.model_validate(payload)


def _source_command_with_range(schema: InstrumentSchema, token: str) -> CommandDef:
    matches = [
        command
        for command in schema.commands
        if command.range is not None
        and "SOUR" in command.command.upper()
        and token in command.command.upper()
    ]
    assert matches, f"Expected a ranged source command containing {token}"
    return sorted(matches, key=lambda command: len(command.command))[0]


@pytest.mark.parametrize("contract_path", _contract_paths(), ids=lambda path: path.name)
def test_web_contract_validates_with_instr_core_schema(contract_path: Path) -> None:
    schema = _load_web_contract(contract_path)

    assert schema.instrument.category == "smu"
    assert schema.instrument.manufacturer
    assert schema.instrument.model


@pytest.mark.parametrize("contract_path", _contract_paths(), ids=lambda path: path.name)
def test_web_contract_declares_limits_and_source_commands(contract_path: Path) -> None:
    schema = _load_web_contract(contract_path)

    assert schema.global_limits.voltage is not None
    assert schema.global_limits.voltage.max > 0
    assert schema.global_limits.current is not None
    assert schema.global_limits.current.max > 0
    assert schema.commands

    voltage_command = _source_command_with_range(schema, "VOLT")
    current_command = _source_command_with_range(schema, "CURR")

    assert voltage_command.range is not None
    assert current_command.range is not None


@pytest.mark.parametrize("contract_path", _contract_paths(), ids=lambda path: path.name)
def test_web_contract_rejects_out_of_range_source_commands(contract_path: Path) -> None:
    schema = _load_web_contract(contract_path)

    voltage_command = _source_command_with_range(schema, "VOLT")
    current_command = _source_command_with_range(schema, "CURR")

    assert voltage_command.range is not None
    assert current_command.range is not None

    voltage_result = validate_command(
        schema,
        voltage_command.command,
        str(voltage_command.range.max + 1),
        {},
    )
    current_result = validate_command(
        schema,
        current_command.command,
        str(current_command.range.max + 1),
        {},
    )

    assert not voltage_result.valid
    assert any(
        "out of range" in issue or "voltage max" in issue
        for issue in voltage_result.issues
    )
    assert not current_result.valid
    assert any(
        "out of range" in issue or "current max" in issue
        for issue in current_result.issues
    )


def test_web_contract_fixture_set_is_not_empty() -> None:
    assert _contract_paths(), "Run scripts/verify-web-contracts.py to sync web fixtures"
