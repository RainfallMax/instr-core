"""Tests for the shared experiment lifecycle."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from instr_core.run_lifecycle import (
    InvalidRunTransition,
    RunStatus,
    can_transition,
    is_terminal,
    transition_run,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.PLANNED, RunStatus.DRY_RUN),
        (RunStatus.DRY_RUN, RunStatus.DRY_RUN),
        (RunStatus.DRY_RUN, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.STOPPING),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.ABORTED),
        (RunStatus.RUNNING, RunStatus.ERROR),
        (RunStatus.STOPPING, RunStatus.ABORTED),
        (RunStatus.STOPPING, RunStatus.ERROR),
    ],
)
def test_allowed_transitions(current: RunStatus, target: RunStatus) -> None:
    assert can_transition(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.PLANNED, RunStatus.RUNNING),
        (RunStatus.DRY_RUN, RunStatus.COMPLETED),
        (RunStatus.COMPLETED, RunStatus.RUNNING),
        (RunStatus.ABORTED, RunStatus.DRY_RUN),
        (RunStatus.ERROR, RunStatus.RUNNING),
    ],
)
def test_forbidden_transitions(current: RunStatus, target: RunStatus) -> None:
    assert can_transition(current, target) is False


def test_transition_updates_timestamps_and_history() -> None:
    run = SimpleNamespace(
        run_id="run-1",
        status=RunStatus.DRY_RUN,
        updated_at="old",
        started_at=None,
        completed_at=None,
        stop_requested_at=None,
        transition_history=[],
    )

    transition_run(run, RunStatus.RUNNING, reason="confirmed", now="2026-01-01T00:00:00Z")
    transition_run(run, RunStatus.COMPLETED, now="2026-01-01T00:01:00Z")

    assert run.status == RunStatus.COMPLETED
    assert run.started_at == "2026-01-01T00:00:00Z"
    assert run.completed_at == "2026-01-01T00:01:00Z"
    assert [item.to_status for item in run.transition_history] == [
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]
    assert run.transition_history[0].reason == "confirmed"


def test_invalid_transition_raises_with_run_context() -> None:
    run = SimpleNamespace(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        transition_history=[],
    )

    with pytest.raises(InvalidRunTransition, match="completed.*running"):
        transition_run(run, RunStatus.RUNNING)


def test_terminal_statuses() -> None:
    assert is_terminal(RunStatus.COMPLETED)
    assert is_terminal(RunStatus.ABORTED)
    assert is_terminal(RunStatus.ERROR)
    assert not is_terminal(RunStatus.RUNNING)


def test_legacy_status_values_migrate() -> None:
    assert RunStatus("failed") == RunStatus.ERROR
    assert RunStatus("idle") == RunStatus.PLANNED
