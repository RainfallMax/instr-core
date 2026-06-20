"""Thread-safe in-memory and on-disk storage for agent runs."""

from __future__ import annotations

import json
import os
import threading
import builtins
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from typing import Any

from .models import AgentRun, DualKeithleyRun, ExperimentType
from ..run_lifecycle import RunStatus, transition_run


class ExecutionReservation(str, Enum):
    """Outcome of an atomic execution reservation."""

    NEW = "new"
    REPLAY = "replay"


@dataclass(frozen=True)
class ReservationResult:
    """Reservation outcome and current persisted run."""

    reservation: ExecutionReservation
    run: Any


class IdempotencyConflict(RuntimeError):
    """An execution reservation conflicts with a previous request."""


class AgentRunStore:
    """Run storage for agent plans and execution records.

    When ``run_dir`` is provided, each run is written as a JSON file and loaded
    on startup. The in-memory dictionary remains the fast path used by API
    handlers.
    """

    def __init__(self, run_dir: Path | str | None = None) -> None:
        self._runs: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._run_dir = Path(run_dir).expanduser() if run_dir is not None else None
        if self._run_dir is not None:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            for path in self._run_dir.glob("*.tmp"):
                path.unlink(missing_ok=True)
            self._load_runs()
            self.recover_interrupted_runs()

    def create(self, run: Any) -> Any:
        """Store a new run."""
        with self._lock:
            if run.run_id in self._runs:
                raise ValueError(f"Run '{run.run_id}' already exists")
            stored = run.model_copy(deep=True)
            self._runs[run.run_id] = stored
            self._persist(stored)
            return stored.model_copy(deep=True)

    def get(self, run_id: str) -> Any | None:
        """Return a run by id."""
        with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run is not None else None

    def update(self, run: Any) -> Any:
        """Replace an existing run."""
        with self._lock:
            stored = run.model_copy(deep=True)
            self._runs[run.run_id] = stored
            self._persist(stored)
            return stored.model_copy(deep=True)

    def list(self) -> list[Any]:
        """Return all stored runs sorted by run id."""
        with self._lock:
            return [
                self._runs[key].model_copy(deep=True)
                for key in sorted(self._runs)
            ]

    def transition(
        self,
        run_id: str,
        target: RunStatus,
        reason: str | None = None,
    ) -> Any:
        """Atomically transition and persist one stored run."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"Run '{run_id}' not found")
            transition_run(run, target, reason=reason)
            self._persist(run)
            return run.model_copy(deep=True)

    def reserve_execution(
        self,
        run_id: str,
        key: str,
        context_fingerprint: str,
    ) -> ReservationResult:
        """Atomically reserve at-most-once execution for a validated run."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"Run '{run_id}' not found")

            if run.execution_idempotency_key is not None:
                if (
                    run.execution_idempotency_key == key
                    and run.execution_context_fingerprint == context_fingerprint
                ):
                    return ReservationResult(
                        ExecutionReservation.REPLAY,
                        run.model_copy(deep=True),
                    )
                raise IdempotencyConflict(
                    f"Run '{run_id}' already has a different execution reservation"
                )

            if run.status != RunStatus.DRY_RUN:
                raise IdempotencyConflict(
                    f"Run '{run_id}' cannot execute from status {run.status.value}"
                )
            if run.validation_context_fingerprint != context_fingerprint:
                raise IdempotencyConflict(
                    "Validation context changed; run dry-run again before execution"
                )
            if run.validation is not None and not run.validation.valid:
                raise IdempotencyConflict("Cannot execute an invalid dry-run")

            run.execution_idempotency_key = key
            run.execution_context_fingerprint = context_fingerprint
            run.execution_attempts = 1
            transition_run(run, RunStatus.RUNNING, reason="execution reserved")
            self._persist(run)
            return ReservationResult(
                ExecutionReservation.NEW,
                run.model_copy(deep=True),
            )

    def recover_interrupted_runs(self) -> builtins.list[str]:
        """Convert persisted active runs to ERROR after process restart."""
        recovered: list[str] = []
        message = (
            "Backend restarted while execution state was active; "
            "hardware state could not be confirmed"
        )
        with self._lock:
            for run in self._runs.values():
                if run.status in {RunStatus.RUNNING, RunStatus.STOPPING}:
                    transition_run(run, RunStatus.ERROR, reason=message)
                    run.error_message = message
                    self._persist(run)
                    recovered.append(run.run_id)
        return recovered

    @property
    def run_dir(self) -> Path | None:
        """Return the persistence directory, if enabled."""
        return self._run_dir

    def _persist(self, run: Any) -> None:
        if self._run_dir is None:
            return
        payload = {
            "kind": _kind_for_run(run),
            "run": run.model_dump(mode="json"),
        }
        path = self._run_dir / f"{run.run_id}.json"
        temp_path = path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)

    def _load_runs(self) -> None:
        if self._run_dir is None:
            return
        for path in sorted(self._run_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                run = _run_from_payload(payload)
            except (OSError, ValueError, TypeError, KeyError):
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                quarantine = path.with_name(f"{path.name}.corrupt-{stamp}")
                try:
                    os.replace(path, quarantine)
                except OSError:
                    pass
                continue
            self._runs[run.run_id] = run


def _kind_for_run(run: Any) -> str:
    if isinstance(run, DualKeithleyRun):
        return "dual_keithley_run"
    if isinstance(run, AgentRun):
        return "agent_run"
    raise TypeError(f"Unsupported run type: {type(run)!r}")


def _run_from_payload(payload: dict[str, Any]) -> Any:
    raw_run = payload["run"]
    kind = payload.get("kind")
    experiment_type = raw_run.get("plan", {}).get("experiment_type")
    if kind == "dual_keithley_run" or experiment_type == ExperimentType.DUAL_KEITHLEY_SWEEP:
        return DualKeithleyRun.model_validate(raw_run)
    return AgentRun.model_validate(raw_run)
