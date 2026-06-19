"""Tests for shared hardware emergency teardown."""

from __future__ import annotations

from instr_core.api.services.safety_service import safe_turn_off_output


class ScriptedVisa:
    """VISA writer with a fixed number of failures."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.commands: list[str] = []

    def write(self, command: str) -> None:
        self.commands.append(command)
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError(f"failed {command}")


def test_teardown_succeeds_on_first_output_off() -> None:
    visa = ScriptedVisa(failures=0)

    report = safe_turn_off_output(visa, "run-1", "USB0::1", sleep=lambda _: None)

    assert report.safe is True
    assert report.attempted_commands == (":OUTP OFF",)
    assert report.successful_command == ":OUTP OFF"
    assert report.errors == ()


def test_teardown_retries_output_off_once() -> None:
    visa = ScriptedVisa(failures=1)

    report = safe_turn_off_output(visa, "run-2", "USB0::2", sleep=lambda _: None)

    assert report.safe is True
    assert report.attempted_commands == (":OUTP OFF", ":OUTP OFF")
    assert report.successful_command == ":OUTP OFF"
    assert len(report.errors) == 1


def test_teardown_uses_reset_after_two_failures() -> None:
    visa = ScriptedVisa(failures=2)

    report = safe_turn_off_output(visa, "run-3", "USB0::3", sleep=lambda _: None)

    assert report.safe is True
    assert report.attempted_commands == (":OUTP OFF", ":OUTP OFF", "*RST")
    assert report.successful_command == "*RST"
    assert len(report.errors) == 2


def test_teardown_reports_critical_failure() -> None:
    visa = ScriptedVisa(failures=3)

    report = safe_turn_off_output(visa, "run-4", "USB0::4", sleep=lambda _: None)

    assert report.safe is False
    assert report.attempted_commands == (":OUTP OFF", ":OUTP OFF", "*RST")
    assert report.successful_command is None
    assert len(report.errors) == 3
