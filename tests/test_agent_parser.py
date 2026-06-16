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
