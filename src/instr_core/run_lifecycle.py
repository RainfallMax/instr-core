"""Shared lifecycle rules for experiment and sweep runs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel


class RunStatus(str, Enum):
    """Canonical lifecycle states for every experiment run."""

    PLANNED = "planned"
    DRY_RUN = "dry_run"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ERROR = "error"
    IDLE = "planned"
    FAILED = "error"

    @classmethod
    def _missing_(cls, value: object) -> RunStatus | None:
        if value == "failed":
            return cls.ERROR
        if value == "idle":
            return cls.PLANNED
        return None


class RunTransition(BaseModel):
    """One persisted lifecycle transition."""

    from_status: RunStatus | None
    to_status: RunStatus
    timestamp: str
    reason: str | None = None


class InvalidRunTransition(ValueError):
    """A requested lifecycle edge is not allowed."""

    def __init__(
        self,
        run_id: str,
        current: RunStatus,
        target: RunStatus,
    ) -> None:
        super().__init__(
            f"Run '{run_id}' cannot transition from {current.value} to {target.value}"
        )
        self.run_id = run_id
        self.current = current
        self.target = target


ALLOWED_TRANSITIONS = {
    RunStatus.PLANNED: {RunStatus.DRY_RUN},
    RunStatus.DRY_RUN: {RunStatus.DRY_RUN, RunStatus.RUNNING},
    RunStatus.RUNNING: {
        RunStatus.STOPPING,
        RunStatus.COMPLETED,
        RunStatus.ABORTED,
        RunStatus.ERROR,
    },
    RunStatus.STOPPING: {RunStatus.ABORTED, RunStatus.ERROR},
    RunStatus.COMPLETED: set(),
    RunStatus.ABORTED: set(),
    RunStatus.ERROR: set(),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    """Return whether a lifecycle edge is allowed."""
    return target in ALLOWED_TRANSITIONS[current]


def is_terminal(status: RunStatus) -> bool:
    """Return whether *status* is immutable and terminal."""
    return status in {RunStatus.COMPLETED, RunStatus.ABORTED, RunStatus.ERROR}


def transition_run(
    run: Any,
    target: RunStatus,
    reason: str | None = None,
    now: str | None = None,
) -> Any:
    """Validate and apply one lifecycle transition."""
    current = RunStatus(run.status)
    if not can_transition(current, target):
        raise InvalidRunTransition(
            getattr(run, "run_id", getattr(run, "session_id", "unknown")),
            current,
            target,
        )

    timestamp = now or datetime.now(timezone.utc).isoformat()
    run.status = target
    if hasattr(run, "updated_at"):
        run.updated_at = timestamp
    if target == RunStatus.RUNNING and hasattr(run, "started_at"):
        run.started_at = timestamp
    if target == RunStatus.STOPPING and hasattr(run, "stop_requested_at"):
        run.stop_requested_at = timestamp
    if is_terminal(target) and hasattr(run, "completed_at"):
        run.completed_at = timestamp

    history = getattr(run, "transition_history", None)
    if history is not None:
        history.append(
            RunTransition(
                from_status=current,
                to_status=target,
                timestamp=timestamp,
                reason=reason,
            )
        )
    return run
