"""Pydantic models for IV sweep configuration, data points, and session state."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator
from ..run_lifecycle import RunStatus, RunTransition


class SweepConfig(BaseModel):
    """User-configurable parameters for an IV sweep.

    ``source_mode`` selects the physical quantity the SMU sources:
    ``VOLT`` sources voltage and measures current (classic IV sweep);
    ``CURR`` sources current and measures voltage (the four-quadrant
    inverse).  ``start_voltage``/``stop_voltage`` always describe the
    sourced quantity regardless of mode, and ``compliance`` always bounds
    the measured quantity.
    """

    start_voltage: float
    stop_voltage: float
    step: float = Field(gt=0)
    compliance: float = Field(gt=0)
    delay_ms: int = Field(default=10, ge=0)
    direction: str = Field(default="UP", pattern="^(UP|DOWN|BOTH)$")
    source_mode: str = Field(default="VOLT", pattern="^(VOLT|CURR)$")

    @model_validator(mode="after")
    def _check_voltage_order(self) -> SweepConfig:
        """Auto-swap start/stop when direction is UP but start > stop."""
        if self.direction == "UP" and self.start_voltage > self.stop_voltage:
            self.start_voltage, self.stop_voltage = self.stop_voltage, self.start_voltage
        return self

    @model_validator(mode="after")
    def _check_point_limit(self) -> SweepConfig:
        """Ensure total points do not exceed 10,000."""
        # Use round-trip via integer steps to avoid fp accumulation error.
        n_steps = int(round(abs(self.stop_voltage - self.start_voltage) / self.step))
        total = n_steps + 1
        if total > 10_000:
            raise ValueError(
                f"Sweep would generate {total} points (max 10,000). "
                "Increase step size or reduce voltage range."
            )
        return self

    def validate_against_schema(self, schema: Any) -> None:
        """Validate the sourced quantity and compliance against schema limits.

        In ``CURR`` mode the sourced quantity is current (bounded by
        ``global_limits.current``) and the compliance is a voltage limit
        (bounded by ``global_limits.voltage``) — the mirror image of ``VOLT``
        mode.

        Args:
            schema: An InstrumentSchema instance (imported lazily to avoid
                circular dependencies).

        Raises:
            ValueError: If a limit is exceeded.
        """
        limits = schema.global_limits
        max_v = max(abs(self.start_voltage), abs(self.stop_voltage))

        if self.source_mode == "CURR":
            if limits.current is not None and max_v > limits.current.max:
                raise ValueError(
                    f"start/stop current exceeds instrument limit: {max_v} > {limits.current.max}"
                )
            if limits.voltage is not None and self.compliance > limits.voltage.max:
                raise ValueError(
                    f"compliance exceeds instrument voltage limit: {self.compliance} > {limits.voltage.max}"
                )
            return

        if limits.voltage is not None and max_v > limits.voltage.max:
            raise ValueError(
                f"start/stop voltage exceeds instrument limit: {max_v} > {limits.voltage.max}"
            )

        if limits.current is not None and self.compliance > limits.current.max:
            raise ValueError(
                f"compliance exceeds instrument limit: {self.compliance} > {limits.current.max}"
            )


class SweepPoint(BaseModel):
    """A single measurement point.

    Field semantics follow the source mode (see ``SweepConfig.source_mode``):

    - ``VOLT`` mode: ``voltage`` is the sourced voltage, ``current`` is the
      measured current.
    - ``CURR`` mode: ``voltage`` holds the sourced *current*, ``current`` holds
      the measured *voltage*.

    ponytail: field names keep the ``VOLT``-mode meaning for backward
    compatibility with existing consumers; renaming to ``source``/``measure``
    is the upgrade path once ``CURR``-mode consumers exist.
    """

    voltage: float
    current: float
    timestamp: str  # ISO 8601


SweepStatus = RunStatus


class SweepResult(BaseModel):
    """Complete result of a sweep."""

    session_id: str
    instrument_key: str
    address: str
    config: SweepConfig
    status: SweepStatus
    points: list[SweepPoint]
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None


class SweepSession(BaseModel):
    """In-memory session tracking a running or completed sweep."""

    model_config = {"arbitrary_types_allowed": True}

    session_id: str
    instrument_key: str
    address: str
    config: SweepConfig
    status: SweepStatus = SweepStatus.IDLE
    points: list[SweepPoint] = Field(default_factory=list)
    error_message: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    stop_requested_at: str | None = None
    transition_history: list[RunTransition] = Field(default_factory=list)

    # Internal: not serialized
    _engine_thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None

    def model_post_init(self, __context: Any) -> None:
        """Initialise internal mutable state after Pydantic validation."""
        self._engine_thread = None
        self._stop_event = None
        if not self.transition_history:
            self.transition_history.append(
                RunTransition(
                    from_status=None,
                    to_status=self.status,
                    timestamp=self.created_at,
                )
            )
