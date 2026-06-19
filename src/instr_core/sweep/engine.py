"""IV sweep execution engine — background-thread sweep with thread-safe state."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from ..safety import TeardownReport, safe_turn_off_output
from .models import SweepConfig, SweepPoint, SweepSession, SweepStatus

logger = logging.getLogger(__name__)


class SweepEngine:
    """Executes IV sweeps in a background thread."""

    def __init__(self) -> None:
        self._sessions: dict[str, SweepSession] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_sweep(
        self,
        session: SweepSession,
        registry: Any,  # Registry
        visa_resource: Any,  # pyvisa.resources.Resource
    ) -> None:
        """Start a sweep in a background thread.

        Args:
            session: The sweep session to populate.
            registry: Instrument registry for schema lookups.
            visa_resource: An open PyVISA resource.
        """
        with self._lock:
            if session.session_id in self._sessions:
                raise RuntimeError(f"Session {session.session_id} already exists")
            self._sessions[session.session_id] = session

        # Prepare threading primitives
        session._stop_event = threading.Event()

        session.status = SweepStatus.RUNNING
        logger.info("Starting sweep %s on %s", session.session_id, session.address)

        thread = threading.Thread(
            target=self._run_sweep,
            args=(session, registry, visa_resource),
            daemon=True,
        )
        session._engine_thread = thread
        thread.start()

    def stop_sweep(self, session_id: str) -> None:
        """Request a running sweep to stop."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        if session._stop_event is not None:
            session._stop_event.set()
            logger.info("Stop requested for sweep %s", session_id)

    def get_session(self, session_id: str) -> SweepSession | None:
        """Get a session by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[SweepSession]:
        """List all sessions, newest first (by created_at)."""
        with self._lock:
            sessions = list(self._sessions.values())
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    # ------------------------------------------------------------------
    # Internal sweep logic
    # ------------------------------------------------------------------

    def _run_sweep(
        self,
        session: SweepSession,
        registry: Any,
        visa: Any,
    ) -> None:
        """The actual sweep logic running in a background thread."""
        try:
            config = session.config

            # 1. Safety initialisation
            visa.write("*RST")
            visa.write(":OUTP OFF")
            visa.write(":SOUR:FUNC VOLT")
            visa.write(f":SENS:CURR:PROT {config.compliance}")

            max_voltage = max(abs(config.start_voltage), abs(config.stop_voltage))
            visa.write(f":SOUR:VOLT:RANG {max_voltage}")
            visa.write(f":SOUR:VOLT {config.start_voltage}")

            # 2. Generate voltage point sequence
            points = self._generate_voltage_points(config)

            # 3. Enable output
            visa.write(":OUTP ON")

            # 4. Scan loop
            for voltage in points:
                if session._stop_event is not None and session._stop_event.is_set():
                    break

                visa.write(f":SOUR:VOLT {voltage}")

                if config.delay_ms > 0:
                    time.sleep(config.delay_ms / 1000.0)

                # Read current with timeout safety
                original_timeout = getattr(visa, "timeout", None)
                try:
                    if original_timeout is not None:
                        visa.timeout = 5000  # 5 seconds
                    resp = visa.query(":READ?").strip()
                finally:
                    if original_timeout is not None:
                        visa.timeout = original_timeout

                # Keithley SMU :READ? may return "current,voltage,time,status"
                # Take the first field (current)
                first_field = resp.split(",")[0].strip()
                current = float(first_field)

                point = SweepPoint(
                    voltage=voltage,
                    current=current,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

                with self._lock:
                    session.points.append(point)

            # 5. Clean shutdown
            self._safe_turn_off_output(visa, session.session_id)

            with self._lock:
                if session._stop_event is not None and session._stop_event.is_set():
                    session.status = SweepStatus.ABORTED
                else:
                    session.status = SweepStatus.COMPLETED
                session.completed_at = datetime.now(timezone.utc).isoformat()

            logger.info(
                "Sweep %s finished with status %s (%d points)",
                session.session_id,
                session.status.value,
                len(session.points),
            )

        except Exception as exc:
            logger.exception("Sweep %s failed: %s", session.session_id, exc)
            self._safe_turn_off_output(visa, session.session_id)
            with self._lock:
                session.status = SweepStatus.ERROR
                session.error_message = str(exc)
                session.completed_at = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_turn_off_output(visa: Any, session_id: str) -> TeardownReport:
        """Delegate output shutdown to the shared safety service."""
        return safe_turn_off_output(visa, session_id)

    @staticmethod
    def _generate_voltage_points(config: SweepConfig) -> list[float]:
        """Generate the voltage sequence from *config*.

        Supports UP, DOWN, and BOTH directions.
        Uses integer-step arithmetic to avoid floating-point accumulation
        errors that can cause missing or extra points.
        """
        start = config.start_voltage
        stop = config.stop_voltage
        step = config.step

        n_steps = int(round(abs(stop - start) / step))
        if start <= stop:
            up_points = [round(start + i * step, 12) for i in range(n_steps + 1)]
            # Ensure exact stop value at the end
            if up_points:
                up_points[-1] = stop
        else:
            up_points = [round(start - i * step, 12) for i in range(n_steps + 1)]
            if up_points:
                up_points[-1] = stop

        if config.direction == "UP":
            return up_points
        if config.direction == "DOWN":
            return list(reversed(up_points))

        # BOTH — up then down (excluding duplicate endpoint)
        down_points = list(reversed(up_points))
        if down_points and up_points and down_points[0] == up_points[-1]:
            down_points = down_points[1:]
        return up_points + down_points
