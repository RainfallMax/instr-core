"""Thread-safe in-memory storage for agent runs."""

from __future__ import annotations

import threading

from .models import AgentRun


class AgentRunStore:
    """In-memory run storage for the first agent release."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._lock = threading.RLock()

    def create(self, run: AgentRun) -> AgentRun:
        """Store a new run."""
        with self._lock:
            self._runs[run.run_id] = run
            return run

    def get(self, run_id: str) -> AgentRun | None:
        """Return a run by id."""
        with self._lock:
            return self._runs.get(run_id)

    def update(self, run: AgentRun) -> AgentRun:
        """Replace an existing run."""
        with self._lock:
            self._runs[run.run_id] = run
            return run
