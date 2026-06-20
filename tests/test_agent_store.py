from __future__ import annotations

import json
import threading

import pytest

from instr_core.agent.models import AgentRunStatus, InstrumentBinding, MeterConfig
from instr_core.agent.planner import create_dual_keithley_run, create_iv_sweep_run
from instr_core.agent.store import (
    AgentRunStore,
    ExecutionReservation,
    IdempotencyConflict,
)
from instr_core.sweep import SweepConfig


def test_agent_run_store_persists_single_device_runs(tmp_path) -> None:
    run_dir = tmp_path / "runs"
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )

    AgentRunStore(run_dir=run_dir).create(run)
    restored = AgentRunStore(run_dir=run_dir).get(run.run_id)

    assert restored is not None
    assert restored.run_id == run.run_id
    assert restored.plan.goal == run.plan.goal
    assert (run_dir / f"{run.run_id}.json").exists()


def test_agent_run_store_persists_dual_device_runs(tmp_path) -> None:
    run_dir = tmp_path / "runs"
    run = create_dual_keithley_run(
        "Sweep with 2600 and read DMM6500",
        InstrumentBinding(address="USB0::SMU::INSTR", instrument_key="keithley/smu/2600"),
        InstrumentBinding(address="USB0::DMM::INSTR", instrument_key="keithley/dmm/dmm6500"),
        SweepConfig(
            start_voltage=0,
            stop_voltage=1,
            step=0.5,
            compliance=0.01,
            delay_ms=0,
            direction="UP",
        ),
        MeterConfig(function="VOLT:DC", range=10),
    )

    AgentRunStore(run_dir=run_dir).create(run)
    restored = AgentRunStore(run_dir=run_dir).get(run.run_id)

    assert restored is not None
    assert restored.run_id == run.run_id
    assert restored.plan.experiment_type == run.plan.experiment_type
    assert restored.plan.source.address == "USB0::SMU::INSTR"


def test_agent_run_store_persists_updates(tmp_path) -> None:
    run_dir = tmp_path / "runs"
    store = AgentRunStore(run_dir=run_dir)
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )
    store.create(run)
    run.status = AgentRunStatus.DRY_RUN
    run.sweep_session_id = "swp-123"

    store.update(run)
    restored = AgentRunStore(run_dir=run_dir).get(run.run_id)

    assert restored is not None
    assert restored.status == AgentRunStatus.DRY_RUN
    assert restored.sweep_session_id == "swp-123"


def test_store_rejects_duplicate_create() -> None:
    store = AgentRunStore()
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )
    store.create(run)

    with pytest.raises(ValueError, match="already exists"):
        store.create(run)


def test_store_get_returns_copy() -> None:
    store = AgentRunStore()
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )
    store.create(run)

    loaded = store.get(run.run_id)
    loaded.error_message = "outside mutation"

    assert store.get(run.run_id).error_message is None


def test_store_transition_is_atomic_under_concurrency() -> None:
    store = AgentRunStore()
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )
    store.create(run)
    store.transition(run.run_id, AgentRunStatus.DRY_RUN)
    barrier = threading.Barrier(8)
    outcomes: list[str] = []

    def transition() -> None:
        barrier.wait()
        try:
            store.transition(run.run_id, AgentRunStatus.RUNNING)
            outcomes.append("ok")
        except Exception:
            outcomes.append("error")

    threads = [threading.Thread(target=transition) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("ok") == 1
    assert store.get(run.run_id).status == AgentRunStatus.RUNNING


def test_persistence_uses_atomic_replace_without_tmp_file(tmp_path) -> None:
    run_dir = tmp_path / "runs"
    store = AgentRunStore(run_dir=run_dir)
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )

    store.create(run)

    assert (run_dir / f"{run.run_id}.json").exists()
    assert not list(run_dir.glob("*.tmp"))


def test_corrupt_run_is_quarantined(tmp_path) -> None:
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    corrupt = run_dir / "run-bad.json"
    corrupt.write_text("{bad json", encoding="utf-8")

    store = AgentRunStore(run_dir=run_dir)

    assert store.list() == []
    assert not corrupt.exists()
    assert list(run_dir.glob("run-bad.json.corrupt-*"))


def test_restart_recovers_active_run_to_error(tmp_path) -> None:
    run_dir = tmp_path / "runs"
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )
    payload = {
        "kind": "agent_run",
        "run": run.model_dump(mode="json") | {"status": "running"},
    }
    run_dir.mkdir()
    (run_dir / f"{run.run_id}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    restored = AgentRunStore(run_dir=run_dir).get(run.run_id)

    assert restored.status == AgentRunStatus.ERROR
    assert "Backend restarted" in restored.error_message


def _dry_run_ready(store: AgentRunStore):
    run = create_iv_sweep_run(
        "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
        "keithley/smu/2600",
        "USB0::INSTR",
    )
    run.validation_context_fingerprint = "fingerprint"
    store.create(run)
    store.transition(run.run_id, AgentRunStatus.DRY_RUN)
    return run


def test_reserve_execution_new_and_same_key_replay() -> None:
    store = AgentRunStore()
    run = _dry_run_ready(store)

    first = store.reserve_execution(run.run_id, "request-key", "fingerprint")
    replay = store.reserve_execution(run.run_id, "request-key", "fingerprint")

    assert first.reservation == ExecutionReservation.NEW
    assert replay.reservation == ExecutionReservation.REPLAY
    assert replay.run.status == AgentRunStatus.RUNNING
    assert replay.run.execution_attempts == 1


def test_reserve_execution_rejects_different_key_or_fingerprint() -> None:
    store = AgentRunStore()
    run = _dry_run_ready(store)
    store.reserve_execution(run.run_id, "request-key", "fingerprint")

    with pytest.raises(IdempotencyConflict):
        store.reserve_execution(run.run_id, "different-key", "fingerprint")
    with pytest.raises(IdempotencyConflict):
        store.reserve_execution(run.run_id, "request-key", "changed")


def test_concurrent_reservations_have_one_new_winner() -> None:
    store = AgentRunStore()
    run = _dry_run_ready(store)
    barrier = threading.Barrier(10)
    outcomes: list[ExecutionReservation | str] = []

    def reserve(index: int) -> None:
        barrier.wait()
        try:
            result = store.reserve_execution(
                run.run_id,
                f"request-{index}",
                "fingerprint",
            )
            outcomes.append(result.reservation)
        except IdempotencyConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=reserve, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count(ExecutionReservation.NEW) == 1
    assert outcomes.count("conflict") == 9
