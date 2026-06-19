"""Unit tests for the IV sweep execution engine.

All tests use MockVisaResource to avoid real hardware dependencies.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from instr_core.sweep.engine import SweepEngine
from instr_core.sweep.models import SweepConfig, SweepPoint, SweepSession, SweepStatus


# ---------------------------------------------------------------------------
# Mock VISA resource
# ---------------------------------------------------------------------------


class MockVisaResource:
    """Mock PyVISA resource for testing sweep engine."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        write_failures: set[str] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._write_failures = set(write_failures or [])
        self._written: list[str] = []
        self.timeout = 3000

    def write(self, cmd: str) -> None:
        self._written.append(cmd)
        if cmd in self._write_failures:
            raise Exception(f"Write failed: {cmd}")

    def query(self, cmd: str) -> str:
        if cmd in self._responses:
            return self._responses[cmd]
        return "1.234567e-6"


class FailingVisa:
    """VISA resource that fails every write."""

    def write(self, cmd: str) -> None:
        raise Exception("Always fails")


class RetryVisa:
    """VISA resource that fails first N writes of a given command."""

    def __init__(self, fail_count: int = 0) -> None:
        self._fail_count = fail_count
        self._written: list[str] = []
        self.timeout = 3000

    def write(self, cmd: str) -> None:
        self._written.append(cmd)
        if self._fail_count > 0:
            self._fail_count -= 1
            raise Exception(f"Write failed: {cmd}")


# ---------------------------------------------------------------------------
# Test _generate_voltage_points
# ---------------------------------------------------------------------------


class TestGenerateVoltagePoints:
    def test_up_normal(self) -> None:
        config = SweepConfig(
            start_voltage=0, stop_voltage=10, step=2.5, compliance=0.01, direction="UP"
        )
        points = SweepEngine._generate_voltage_points(config)
        assert points == [0.0, 2.5, 5.0, 7.5, 10.0]

    def test_up_auto_swap(self) -> None:
        # start > stop with UP direction is auto-swapped by the model validator,
        # so the engine receives start < stop. We test the engine directly with
        # start > stop to verify it handles raw input correctly.
        config = SweepConfig(
            start_voltage=0, stop_voltage=10, step=2.5, compliance=0.01, direction="UP"
        )
        # Manually override to simulate pre-validator state
        config.start_voltage = 10
        config.stop_voltage = 0
        points = SweepEngine._generate_voltage_points(config)
        # Engine should generate points from 10 down to 0 (raw behavior)
        assert points[0] == 10.0
        assert points[-1] == 0.0

    def test_down(self) -> None:
        config = SweepConfig(
            start_voltage=0, stop_voltage=10, step=2.5, compliance=0.01, direction="DOWN"
        )
        points = SweepEngine._generate_voltage_points(config)
        assert points == [10.0, 7.5, 5.0, 2.5, 0.0]

    def test_both_no_duplicate(self) -> None:
        config = SweepConfig(
            start_voltage=0, stop_voltage=5, step=2.5, compliance=0.01, direction="BOTH"
        )
        points = SweepEngine._generate_voltage_points(config)
        # up (3) + down (3) - 1 duplicate endpoint = 5 points
        assert len(points) == 5
        assert points == [0.0, 2.5, 5.0, 2.5, 0.0]

    def test_floating_point_precision(self) -> None:
        config = SweepConfig(
            start_voltage=0, stop_voltage=1, step=0.1, compliance=0.01, direction="UP"
        )
        points = SweepEngine._generate_voltage_points(config)
        assert len(points) == 11
        assert abs(points[-1] - 1.0) < 1e-10  # Last point should be exactly 1.0

    def test_single_point(self) -> None:
        config = SweepConfig(
            start_voltage=5, stop_voltage=5, step=1, compliance=0.01, direction="UP"
        )
        points = SweepEngine._generate_voltage_points(config)
        assert points == [5.0]

    def test_negative_voltages(self) -> None:
        config = SweepConfig(
            start_voltage=-10,
            stop_voltage=-5,
            step=2.5,
            compliance=0.01,
            direction="UP",
        )
        points = SweepEngine._generate_voltage_points(config)
        assert points == [-10.0, -7.5, -5.0]


# ---------------------------------------------------------------------------
# Test _safe_turn_off_output
# ---------------------------------------------------------------------------


class TestSafeTurnOffOutput:
    def test_first_attempt_succeeds(self, caplog: pytest.LogCaptureFixture) -> None:
        visa = MockVisaResource()
        with caplog.at_level(logging.INFO):
            report = SweepEngine._safe_turn_off_output(visa, "test-session")
        assert report.safe is True
        assert ":OUTP OFF" in visa._written[0]
        assert any("succeeded" in record.message for record in caplog.records)

    def test_second_attempt_succeeds(self, caplog: pytest.LogCaptureFixture) -> None:
        visa = RetryVisa(fail_count=1)
        with caplog.at_level(logging.WARNING):
            SweepEngine._safe_turn_off_output(visa, "test-session")
        assert len(visa._written) == 2  # First fails, second succeeds
        assert visa._written[0] == ":OUTP OFF"
        assert visa._written[1] == ":OUTP OFF"
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert not any(record.levelno == logging.CRITICAL for record in caplog.records)

    def test_all_attempts_fail_logs_critical(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.CRITICAL):
            SweepEngine._safe_turn_off_output(FailingVisa(), "test-session")
        assert any(record.levelno == logging.CRITICAL for record in caplog.records)
        assert any(
            "output may still be ON" in record.message for record in caplog.records
        )

    def test_rst_fallback_succeeds(self, caplog: pytest.LogCaptureFixture) -> None:
        # First two :OUTP OFF fail, *RST succeeds
        visa = RetryVisa(fail_count=2)
        with caplog.at_level(logging.INFO):
            SweepEngine._safe_turn_off_output(visa, "test-session")
        assert len(visa._written) == 3
        assert visa._written[0] == ":OUTP OFF"
        assert visa._written[1] == ":OUTP OFF"
        assert visa._written[2] == "*RST"
        assert any("*RST fallback succeeded" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Test sweep engine lifecycle
# ---------------------------------------------------------------------------


class TestSweepEngineLifecycle:
    def test_start_sweep_creates_session(self) -> None:
        engine = SweepEngine()
        config = SweepConfig(
            start_voltage=0, stop_voltage=5, step=2.5, compliance=0.01, direction="UP"
        )
        session = SweepSession(
            session_id="start-test",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        engine.start_sweep(session, None, visa)
        assert session.status == SweepStatus.RUNNING
        assert session.session_id in engine._sessions
        # Clean up
        session._engine_thread.join(timeout=2.0)

    def test_start_duplicate_raises(self) -> None:
        engine = SweepEngine()
        config = SweepConfig(
            start_voltage=0, stop_voltage=5, step=2.5, compliance=0.01, direction="UP"
        )
        session = SweepSession(
            session_id="dup",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        engine.start_sweep(session, None, visa)
        with pytest.raises(RuntimeError, match="already exists"):
            engine.start_sweep(session, None, visa)
        # Clean up
        session._engine_thread.join(timeout=2.0)

    def test_stop_sweep_sets_event(self) -> None:
        engine = SweepEngine()
        config = SweepConfig(
            start_voltage=0, stop_voltage=10, step=2.5, compliance=0.01, direction="UP"
        )
        session = SweepSession(
            session_id="stop-test",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        engine.start_sweep(session, None, visa)
        engine.stop_sweep("stop-test")
        assert session._stop_event.is_set()
        # Clean up
        session._engine_thread.join(timeout=2.0)

    def test_get_session_existing(self) -> None:
        engine = SweepEngine()
        config = SweepConfig(
            start_voltage=0, stop_voltage=5, step=2.5, compliance=0.01, direction="UP"
        )
        session = SweepSession(
            session_id="get-test",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        engine._sessions["get-test"] = session
        assert engine.get_session("get-test") is session

    def test_get_session_missing(self) -> None:
        engine = SweepEngine()
        assert engine.get_session("missing") is None

    def test_list_sessions_order(self) -> None:
        engine = SweepEngine()
        config = SweepConfig(
            start_voltage=0, stop_voltage=5, step=2.5, compliance=0.01, direction="UP"
        )
        s1 = SweepSession(
            session_id="old",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
            created_at="2026-01-01T00:00:00Z",
        )
        s2 = SweepSession(
            session_id="new",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
            created_at="2026-01-02T00:00:00Z",
        )
        engine._sessions["old"] = s1
        engine._sessions["new"] = s2
        result = engine.list_sessions()
        assert result[0].session_id == "new"
        assert result[1].session_id == "old"


# ---------------------------------------------------------------------------
# Test _run_sweep with mock VISA
# ---------------------------------------------------------------------------


class TestRunSweepMock:
    def test_normal_sweep_3_points(self) -> None:
        config = SweepConfig(
            start_voltage=0,
            stop_voltage=5,
            step=2.5,
            compliance=0.01,
            direction="UP",
            delay_ms=0,
        )
        session = SweepSession(
            session_id="normal",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        engine = SweepEngine()
        engine._run_sweep(session, None, visa)
        assert session.status == SweepStatus.COMPLETED
        assert len(session.points) == 3
        assert session.points[0].voltage == 0.0
        assert session.points[-1].voltage == 5.0
        assert ":OUTP OFF" in visa._written

    def test_multi_value_read_response(self) -> None:
        config = SweepConfig(
            start_voltage=0,
            stop_voltage=2.5,
            step=2.5,
            compliance=0.01,
            direction="UP",
            delay_ms=0,
        )
        session = SweepSession(
            session_id="multi",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource(responses={":READ?": "1.23e-6,5.0,0.001,0"})
        engine = SweepEngine()
        engine._run_sweep(session, None, visa)
        assert len(session.points) == 2
        assert session.points[0].current == 1.23e-6

    def test_stop_mid_sweep(self) -> None:
        config = SweepConfig(
            start_voltage=0,
            stop_voltage=10,
            step=2.5,
            compliance=0.01,
            direction="UP",
            delay_ms=0,
        )
        session = SweepSession(
            session_id="stop",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        engine = SweepEngine()
        engine.start_sweep(session, None, visa)
        # Wait a tiny bit for thread to start
        time.sleep(0.05)
        engine.stop_sweep("stop")
        session._engine_thread.join(timeout=2.0)
        assert session.status in (SweepStatus.ABORTED, SweepStatus.COMPLETED)
        assert ":OUTP OFF" in visa._written

    def test_exception_mid_sweep_output_off(self) -> None:
        config = SweepConfig(
            start_voltage=0,
            stop_voltage=10,
            step=2.5,
            compliance=0.01,
            direction="UP",
            delay_ms=0,
        )
        session = SweepSession(
            session_id="error",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        # Make query fail after first point
        original_query = visa.query
        call_count = [0]

        def failing_query(cmd: str) -> str:
            call_count[0] += 1
            if call_count[0] > 2:  # First :READ? succeeds, second fails
                raise Exception("Query failed")
            return original_query(cmd)

        visa.query = failing_query  # type: ignore[method-assign]

        engine = SweepEngine()
        engine._run_sweep(session, None, visa)
        assert session.status == SweepStatus.ERROR
        assert ":OUTP OFF" in visa._written

    def test_timeout_restored(self) -> None:
        config = SweepConfig(
            start_voltage=0,
            stop_voltage=2.5,
            step=2.5,
            compliance=0.01,
            direction="UP",
            delay_ms=0,
        )
        session = SweepSession(
            session_id="timeout",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        visa = MockVisaResource()
        original_timeout = visa.timeout
        engine = SweepEngine()
        engine._run_sweep(session, None, visa)
        assert visa.timeout == original_timeout  # Should be restored


# ---------------------------------------------------------------------------
# Test thread safety
# ---------------------------------------------------------------------------


class TestSweepEngineThreadSafety:
    def test_concurrent_reads_no_exception(self) -> None:
        engine = SweepEngine()
        config = SweepConfig(
            start_voltage=0, stop_voltage=5, step=2.5, compliance=0.01, direction="UP"
        )
        session = SweepSession(
            session_id="thread",
            instrument_key="keithley/smu/2600",
            address="TEST",
            config=config,
        )
        # Pre-populate points
        session.points = [
            SweepPoint(
                voltage=float(i),
                current=1e-6,
                timestamp="2026-01-01T00:00:00Z",
            )
            for i in range(100)
        ]
        engine._sessions["thread"] = session

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(100):
                    s = engine.get_session("thread")
                    _ = list(s.points)  # Read all points
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety errors: {errors}"
