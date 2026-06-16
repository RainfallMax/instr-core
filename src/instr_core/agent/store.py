"""Thread-safe in-memory storage for agent runs."""

from __future__ import annotations

import threading

from typing import Any


class AgentRunStore:
    """In-memory run storage for the first agent release."""

    def __init__(self) -> None:
        self._runs: dict[str, Any] = {}
        self._lock = threading.RLock()

    def create(self, run: Any) -> Any:
        """Store a new run."""
        with self._lock:
            self._runs[run.run_id] = run
            return run

    def get(self, run_id: str) -> Any | None:
        """Return a run by id."""
        with self._lock:
            return self._runs.get(run_id)

    def update(self, run: Any) -> Any:
        """Replace an existing run."""
        with self._lock:
            self._runs[run.run_id] = run
            return run
