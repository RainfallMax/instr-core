from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from instr_core.agent.store import AgentRunStore
from instr_core.api.services.ownership_service import AddressOwnershipRegistry
from instr_core.api_server import create_api_app
from instr_core.sweep import SweepEngine
from instr_core.validator import Registry

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"


class MockResource:
    def __init__(
        self,
        idn_response: str = "KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1,1.0",
    ) -> None:
        self._idn = idn_response
        self.written: list[str] = []

    def query(self, cmd: str) -> str:
        if cmd == "*IDN?":
            return self._idn
        return "0.001,0,0,0"

    def write(self, cmd: str) -> None:
        self.written.append(cmd)


class MockResourceManager:
    def __init__(self) -> None:
        self.resource = MockResource()

    def list_resources(self) -> tuple[str, ...]:
        return ("USB0::INSTR",)

    def open_resource(self, address: str) -> MockResource:
        return self.resource


def make_client() -> TestClient:
    app = create_api_app()
    app.state.registry = Registry.load(FIXTURES_ROOT)
    app.state.sweep_engine = SweepEngine()
    app.state.agent_store = AgentRunStore()
    app.state.address_lock = threading.RLock()
    app.state.address_to_schema = {}
    app.state.address_state = {}
    return TestClient(app)


def connect_keithley(client: TestClient, mock_pyvisa: MagicMock) -> None:
    mock_pyvisa.ResourceManager.return_value = MockResourceManager()
    response = client.post("/visa/connect", params={"address": "USB0::INSTR"})
    assert response.status_code == 200
    assert response.json()["schema_key"] == "keithley/smu/2600"


@patch("instr_core.api_server.pyvisa")
def test_agent_plan_and_dry_run(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)

    plan_response = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 5V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    )

    assert plan_response.status_code == 200
    run = plan_response.json()["run"]
    assert run["status"] == "planned"
    assert run["plan"]["instrument_key"] == "keithley/smu/2600"

    dry_response = client.post("/agent/dry-run", json={"run_id": run["run_id"]})

    assert dry_response.status_code == 200
    dry_run = dry_response.json()["run"]
    assert dry_run["status"] == "dry_run"
    assert dry_run["validation"]["valid"] is True
    assert dry_run["validation"]["estimated_points"] == 11
    assert ":OUTP ON" in dry_run["validation"]["commands"]


@patch("instr_core.api_server.pyvisa")
def test_agent_dry_run_rejects_over_limit_voltage(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)

    plan_response = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 50V in 1V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    )
    run_id = plan_response.json()["run"]["run_id"]

    dry_response = client.post("/agent/dry-run", json={"run_id": run_id})

    assert dry_response.status_code == 200
    validation = dry_response.json()["run"]["validation"]
    assert validation["valid"] is False
    assert any("Voltage exceeds" in issue for issue in validation["issues"])


@patch("instr_core.api_server.pyvisa")
def test_agent_execute_requires_confirmation(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    plan_response = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    )
    run_id = plan_response.json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})

    execute_response = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": False},
        headers={"Idempotency-Key": "single-confirm-test"},
    )

    assert execute_response.status_code == 400
    assert "confirm=true" in execute_response.json()["detail"]


@patch("instr_core.api_server.pyvisa")
def test_agent_execute_starts_sweep_after_valid_dry_run(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    plan_response = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    )
    run_id = plan_response.json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})

    execute_response = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers={"Idempotency-Key": "single-execute-test"},
    )

    assert execute_response.status_code == 200
    run = execute_response.json()["run"]
    assert run["status"] == "running"
    assert run["sweep_session_id"] is not None
    session = client.app.state.sweep_engine.get_session(run["sweep_session_id"])
    assert session is not None
    session._engine_thread.join(timeout=2)
    assert client.app.state.address_ownership.snapshot() == {}
    stored = client.get(f"/agent/runs/{run_id}").json()["run"]
    assert stored["status"] == "completed"


@patch("instr_core.api_server.pyvisa")
def test_agent_execute_requires_idempotency_key(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    run_id = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    ).json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})

    response = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@patch("instr_core.api_server.pyvisa")
def test_agent_same_key_replay_does_not_execute_twice(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    rm = mock_pyvisa.ResourceManager.return_value
    run_id = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    ).json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})
    headers = {"Idempotency-Key": "same-key-replay"}

    first = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers=headers,
    )
    session = client.app.state.sweep_engine.get_session(first.json()["run"]["sweep_session_id"])
    session._engine_thread.join(timeout=2)
    second = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers=headers,
    )

    assert second.status_code == 200
    assert rm.resource.written.count(":OUTP ON") == 1


@patch("instr_core.api_server.pyvisa")
def test_agent_rejects_stale_validation_context(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    run_id = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    ).json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})
    client.app.state.address_state["USB0::INSTR"]["output"] = "ON"

    response = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers={"Idempotency-Key": "stale-context"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VALIDATION_CONTEXT_STALE"


@patch("instr_core.api_server.pyvisa")
def test_agent_owned_address_marks_reserved_run_error(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    run_id = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    ).json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})
    client.app.state.address_ownership = AddressOwnershipRegistry()
    client.app.state.address_ownership.acquire("USB0::INSTR", "existing-run")

    response = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers={"Idempotency-Key": "single-owned-test"},
    )

    assert response.status_code == 409
    stored = client.get(f"/agent/runs/{run_id}").json()["run"]
    assert stored["status"] == "error"
    assert "already owned" in stored["error_message"]


@patch("instr_core.api_server.pyvisa")
def test_agent_stop_transitions_to_aborted(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    run_id = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 10V in 0.1V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    ).json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})
    execute = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers={"Idempotency-Key": "single-stop-test"},
    )

    stopped = client.post(f"/agent/runs/{run_id}/stop")
    session_id = execute.json()["run"]["sweep_session_id"]
    session = client.app.state.sweep_engine.get_session(session_id)
    session._engine_thread.join(timeout=2)
    stored = client.get(f"/agent/runs/{run_id}").json()["run"]

    assert stopped.status_code == 200
    assert stopped.json()["run"]["status"] in {"stopping", "aborted"}
    assert stored["status"] == "aborted"


@patch("instr_core.api_server.pyvisa")
def test_terminal_agent_cannot_be_stopped(mock_pyvisa: MagicMock) -> None:
    client = make_client()
    connect_keithley(client, mock_pyvisa)
    run_id = client.post(
        "/agent/plan",
        json={
            "goal": "Sweep 0V to 1V in 0.5V steps with 10mA compliance",
            "address": "USB0::INSTR",
        },
    ).json()["run"]["run_id"]
    client.post("/agent/dry-run", json={"run_id": run_id})
    execute = client.post(
        "/agent/execute",
        json={"run_id": run_id, "confirm": True},
        headers={"Idempotency-Key": "terminal-stop-test"},
    )
    session = client.app.state.sweep_engine.get_session(
        execute.json()["run"]["sweep_session_id"]
    )
    session._engine_thread.join(timeout=2)

    response = client.post(f"/agent/runs/{run_id}/stop")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RUN_STATE_CONFLICT"
