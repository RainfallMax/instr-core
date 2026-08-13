from __future__ import annotations

import pytest

from instr_core.agent.parser import AgentParseError, parse_iv_sweep_goal


def test_parse_iv_sweep_goal_with_basic_units() -> None:
    result = parse_iv_sweep_goal(
        "Sweep 0V to 5V in 0.1V steps with 10mA compliance and 20ms delay"
    )

    assert result.start_voltage == 0
    assert result.stop_voltage == 5
    assert result.step == 0.1
    assert result.compliance == 0.01
    assert result.delay_ms == 20
    assert result.direction == "UP"


def test_parse_iv_sweep_goal_with_microamps_and_millivolts() -> None:
    result = parse_iv_sweep_goal(
        "Sweep 0 mV to 500 mV step 50 mV compliance 100 uA direction up"
    )

    assert result.start_voltage == 0
    assert result.stop_voltage == 0.5
    assert result.step == 0.05
    assert result.compliance == 100e-6
    assert result.direction == "UP"


def test_parse_iv_sweep_goal_rejects_missing_compliance() -> None:
    with pytest.raises(AgentParseError, match="compliance"):
        parse_iv_sweep_goal("Sweep 0V to 5V in 0.1V steps")


def test_parse_iv_sweep_goal_rejects_missing_step() -> None:
    with pytest.raises(AgentParseError, match="step"):
        parse_iv_sweep_goal("Sweep 0V to 5V with 10mA compliance")


def test_parse_current_sweep_goal_detects_source_mode() -> None:
    result = parse_iv_sweep_goal(
        "Source current from 0A to 1A in 0.1A steps, measure voltage, "
        "20V compliance, 10ms delay"
    )

    assert result.source_mode == "CURR"
    assert result.start_voltage == 0.0
    assert result.stop_voltage == 1.0
    assert result.step == 0.1
    assert result.compliance == 20.0
    assert result.delay_ms == 10


def test_current_sweep_intent_to_sweep_config() -> None:
    result = parse_iv_sweep_goal("current sweep 0A to 1A step 0.1A compliance 20V")
    config = result.to_sweep_config()

    assert config.source_mode == "CURR"
    assert config.start_voltage == 0.0
    assert config.stop_voltage == 1.0
    assert config.compliance == 20.0


def test_voltage_sweep_defaults_to_volt_mode() -> None:
    result = parse_iv_sweep_goal("Sweep 0V to 5V in 0.1V steps with 10mA compliance")

    assert result.source_mode == "VOLT"
