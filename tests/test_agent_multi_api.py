from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from instr_core.agent.models import DualKeithleyPlanRequest
from instr_core.agent.store import AgentRunStore
from instr_core.api_server import create_api_app
from instr_core.sweep import SweepEngine
from instr_core.validator import Registry

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"

DMM6500_SCHEMA = """
instrument:
  manufacturer: Keithley
  model: "DMM6500"
  category: dmm
  description: "Test DMM6500 schema"

global_limits:
  voltage: {max: 1000.0, unit: "VDC"}
  current: {max: 10.0, unit: "A"}

commands:
  - command: ":CONF:VOLT:DC"
    description: "Configure DC voltage measurement"
    parameters: []
    sets_state:
      function: "VOLT:DC"
    tags: ["setup", "measure", "voltage"]

  - command: ":SENS:VOLT:DC:RANG"
    description: "Set DC voltage range"
    parameters:
      - name: "range"
        type: "float"
    range:
      min: 0.0
      max: 1000.0
    requires:
      function: "VOLT:DC"
    sets_state:
      ":SENS:VOLT:DC:RANG": "$ARGUMENT"
    tags: ["setup", "measure", "voltage"]

  - command: ":READ?"
    description: "Read one configured measurement"
    parameters: []
    safety:
      sequence:
        - before: ":READ?"
          require_state_keys_present: ["function"]
          message: "Measurement function must be configured before reading"
    tags: ["measure", "read"]
"""


class MultiMockResource:
    def __init__(self, idn_response: str, read_response: str = "1.234") -> None:
        self._idn = idn_response
        self._read_response = read_response
        self.written: list[str] = []
        self.query_log: list[str] = []

    def query(self, cmd: str) -> str:
        self.query_log.append(cmd)
        if cmd == "*IDN?":
            return self._idn
        if cmd == ":READ?":
            return self._read_response
        return "0"

    def write(self, cmd: str) -> None:
        self.written.append(cmd)


class MultiMockResourceManager:
    def __init__(self) -> None:
        self.resources = {
            "USB0::SMU::INSTR": MultiMockResource(
                "KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1,1.0"
            ),
            "USB0::DMM::INSTR": MultiMockResource(
                "KEITHLEY INSTRUMENTS,DMM6500,2,1.0",
                read_response="2.500",
            ),
        }
        self.opened: list[str] = []

    def list_resources(self) -> tuple[str, ...]:
        return tuple(self.resources.keys())

    def open_resource(self, address: str) -> MultiMockResource:
        self.opened.append(address)
        return self.resources[address]


def make_registry(tmp_path: Path) -> Registry:
    registry_root = tmp_path / "registry"
    dmm_dir = registry_root / "keithley" / "dmm"
    dmm_dir.mkdir(parents=True)
    (dmm_dir / "dmm6500.yaml").write_text(DMM6500_SCHEMA, encoding="utf-8")

    # Reuse the existing 2600 fixture without copying it into the project tree.
    return Registry.load(FIXTURES_ROOT, registry_root)


def make_client(tmp_path: Path) -> TestClient:
    app = create_api_app()
    app.state.registry = make_registry(tmp_path)
    app.state.sweep_engine = SweepEngine()
    app.state.agent_store = AgentRunStore()
    app.state.address_lock = threading.RLock()
    app.state.address_to_schema = {
        "USB0::SMU::INSTR": "keithley/smu/2600",
        "USB0::DMM::INSTR": "keithley/dmm/dmm6500",
    }
    app.state.address_state = {
        "USB0::SMU::INSTR": {},
        "USB0::DMM::INSTR": {},
    }
    return TestClient(app)


def plan_payload() -> dict:
    return {
        "goal": "Sweep 0V to 1V in 0.5V steps and measure DUT voltage with DMM6500",
        "source": {
            "address": "USB0::SMU::INSTR",
            "instrument_key": "keithley/smu/2600",
        },
        "meter": {
            "address": "USB0::DMM::INSTR",
            "instrument_key": "keithley/dmm/dmm6500",
        },
        "source_config": {
            "start_voltage": 0,
            "stop_voltage": 1,
            "step": 0.5,
            "compliance": 0.01,
            "delay_ms": 0,
            "direction": "UP",
        },
        "meter_config": {
            "function": "VOLT:DC",
            "range": 10,
        },
    }


@patch("instr_core.api_server.pyvisa")
def test_multi_agent_plan_and_dry_run_do_not_open_visa(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    rm = MultiMockResourceManager()
    mock_pyvisa.ResourceManager.return_value = rm
    client = make_client(tmp_path)

    plan_response = client.post("/agent/multi/plan", json=plan_payload())

    assert plan_response.status_code == 200
    run = plan_response.json()["run"]
    assert run["plan"]["experiment_type"] == "dual_keithley_sweep"

    dry_response = client.post("/agent/multi/dry-run", json={"run_id": run["run_id"]})

    assert dry_response.status_code == 200
    dry_run = dry_response.json()["run"]
    assert dry_run["status"] == "dry_run"
    assert dry_run["validation"]["valid"] is True
    assert dry_run["validation"]["estimated_points"] == 3
    assert rm.opened == []


@patch("instr_core.api_server.pyvisa")
def test_multi_agent_dry_run_rejects_meter_range_over_limit(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    mock_pyvisa.ResourceManager.return_value = MultiMockResourceManager()
    client = make_client(tmp_path)
    payload = plan_payload()
    payload["meter_config"]["range"] = 1200

    plan_response = client.post("/agent/multi/plan", json=payload)
    run_id = plan_response.json()["run"]["run_id"]
    dry_response = client.post("/agent/multi/dry-run", json={"run_id": run_id})

    validation = dry_response.json()["run"]["validation"]
    assert validation["valid"] is False
    assert any("DMM6500" in issue or "meter" in issue.lower() for issue in validation["issues"])


@patch("instr_core.api_server.pyvisa")
def test_multi_agent_execute_requires_confirmation(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    mock_pyvisa.ResourceManager.return_value = MultiMockResourceManager()
    client = make_client(tmp_path)
    plan_response = client.post("/agent/multi/plan", json=plan_payload())
    run_id = plan_response.json()["run"]["run_id"]
    client.post("/agent/multi/dry-run", json={"run_id": run_id})

    execute_response = client.post(
        "/agent/multi/execute",
        json={"run_id": run_id, "confirm": False},
    )

    assert execute_response.status_code == 400
    assert "confirm=true" in execute_response.json()["detail"]


@patch("instr_core.api_server.pyvisa")
def test_multi_agent_execute_records_points_and_turns_output_off(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    rm = MultiMockResourceManager()
    mock_pyvisa.ResourceManager.return_value = rm
    client = make_client(tmp_path)
    plan_response = client.post("/agent/multi/plan", json=plan_payload())
    run_id = plan_response.json()["run"]["run_id"]
    client.post("/agent/multi/dry-run", json={"run_id": run_id})

    execute_response = client.post(
        "/agent/multi/execute",
        json={"run_id": run_id, "confirm": True},
    )

    assert execute_response.status_code == 200
    run = execute_response.json()["run"]
    assert run["status"] == "completed"
    assert len(run["result"]["points"]) == 3
    assert run["result"]["summary"]["points"] == 3
    assert rm.resources["USB0::SMU::INSTR"].written[-1] == ":OUTP OFF"
    assert rm.resources["USB0::DMM::INSTR"].query_log.count(":READ?") == 3


@patch("instr_core.api_server.pyvisa")
def test_multi_agent_export_returns_csv_after_execution(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    mock_pyvisa.ResourceManager.return_value = MultiMockResourceManager()
    client = make_client(tmp_path)
    plan_response = client.post("/agent/multi/plan", json=plan_payload())
    run_id = plan_response.json()["run"]["run_id"]
    client.post("/agent/multi/dry-run", json={"run_id": run_id})
    client.post(
        "/agent/multi/execute",
        json={"run_id": run_id, "confirm": True},
    )

    export_response = client.get(f"/agent/multi/runs/{run_id}/export")

    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in export_response.headers["content-disposition"]
    assert export_response.text.splitlines()[0] == "Source Voltage(V),Meter Value,Timestamp"
    assert "0.000000,2.500000e+00" in export_response.text


class FakeStructuredPlanner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def plan_dual_keithley(self, goal: str) -> DualKeithleyPlanRequest:
        self.calls.append(goal)
        return DualKeithleyPlanRequest.model_validate(plan_payload() | {"goal": goal})


@patch("instr_core.api_server.pyvisa")
def test_llm_agent_plan_creates_dual_run_without_opening_visa(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    rm = MultiMockResourceManager()
    mock_pyvisa.ResourceManager.return_value = rm
    client = make_client(tmp_path)
    client.app.state.llm_planner = FakeStructuredPlanner()

    response = client.post(
        "/agent/llm/plan",
        json={
            "goal": "Use the 2600 to sweep 0 to 1 V and read voltage on DMM6500.",
            "experiment_type": "dual_keithley_sweep",
        },
    )

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "planned"
    assert run["plan"]["experiment_type"] == "dual_keithley_sweep"
    assert run["plan"]["source"]["instrument_key"] == "keithley/smu/2600"
    assert rm.opened == []


@patch("instr_core.api_server.pyvisa")
def test_agent_runs_lists_recorded_multi_runs(
    mock_pyvisa: MagicMock,
    tmp_path: Path,
) -> None:
    mock_pyvisa.ResourceManager.return_value = MultiMockResourceManager()
    client = make_client(tmp_path)
    plan_response = client.post("/agent/multi/plan", json=plan_payload())
    run_id = plan_response.json()["run"]["run_id"]

    list_response = client.get("/agent/runs")

    assert list_response.status_code == 200
    runs = list_response.json()["runs"]
    assert any(
        item["run_id"] == run_id
        and item["experiment_type"] == "dual_keithley_sweep"
        and item["status"] == "planned"
        for item in runs
    )
