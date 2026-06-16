"""Thread-safe in-memory and on-disk storage for agent runs."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from typing import Any

from .models import AgentRun, DualKeithleyRun, ExperimentType


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
            self._load_runs()

    def create(self, run: Any) -> Any:
        """Store a new run."""
        with self._lock:
            self._runs[run.run_id] = run
            self._persist(run)
            return run

    def get(self, run_id: str) -> Any | None:
        """Return a run by id."""
        with self._lock:
            return self._runs.get(run_id)

    def update(self, run: Any) -> Any:
        """Replace an existing run."""
        with self._lock:
            self._runs[run.run_id] = run
            self._persist(run)
            return run

    def list(self) -> list[Any]:
        """Return all stored runs sorted by run id."""
        with self._lock:
            return [self._runs[key] for key in sorted(self._runs)]

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
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _load_runs(self) -> None:
        if self._run_dir is None:
            return
        for path in sorted(self._run_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                run = _run_from_payload(payload)
            except (OSError, ValueError, TypeError, KeyError):
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
