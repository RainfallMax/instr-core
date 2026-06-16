from __future__ import annotations

from instr_core.agent.models import AgentRunStatus, InstrumentBinding, MeterConfig
from instr_core.agent.planner import create_dual_keithley_run, create_iv_sweep_run
from instr_core.agent.store import AgentRunStore
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
    run.status = AgentRunStatus.RUNNING
    run.sweep_session_id = "swp-123"

    store.update(run)
    restored = AgentRunStore(run_dir=run_dir).get(run.run_id)

    assert restored is not None
    assert restored.status == AgentRunStatus.RUNNING
    assert restored.sweep_session_id == "swp-123"
