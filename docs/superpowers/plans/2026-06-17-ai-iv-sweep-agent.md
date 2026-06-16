# AI IV Sweep Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Agent API-first IV sweep workflow that parses natural language into a safe dry-run plan and executes only after confirmation.

**Architecture:** Add a focused `instr_core.agent` package for models, parsing, planning, validation, and in-memory run storage. Add a thin FastAPI `agent` route that uses existing app dependencies, registry, address/schema mapping, VISA service, and `SweepEngine`. Keep execution delegated to existing sweep infrastructure.

**Tech Stack:** Python 3.12+, Pydantic v2, FastAPI, existing `SweepConfig`, `SweepEngine`, `Registry`, and validator functions.

---

## File Structure

- Create `src/instr_core/agent/__init__.py`: public exports for agent models and services.
- Create `src/instr_core/agent/models.py`: Pydantic models for requests, plans, dry-run results, execution, and runs.
- Create `src/instr_core/agent/parser.py`: deterministic IV sweep natural-language parser with unit conversion.
- Create `src/instr_core/agent/planner.py`: plan creation, command preview, dry-run validation, and execute precondition checks.
- Create `src/instr_core/agent/store.py`: thread-safe in-memory `AgentRunStore`.
- Create `src/instr_core/api/routes/agent.py`: FastAPI endpoints under `/agent`.
- Modify `src/instr_core/api/routes/__init__.py`: export `agent_router`.
- Modify `src/instr_core/api_server.py`: include the agent router.
- Modify `src/instr_core/api/dependencies.py`: initialize `AgentRunStore` and expose dependency.
- Create `tests/test_agent_parser.py`: parser unit tests.
- Create `tests/test_agent_api.py`: API dry-run and execute behavior tests.

## Task 1: Agent Models and Parser

**Files:**
- Create: `src/instr_core/agent/__init__.py`
- Create: `src/instr_core/agent/models.py`
- Create: `src/instr_core/agent/parser.py`
- Test: `tests/test_agent_parser.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_agent_parser.py`:

```python
from __future__ import annotations

import pytest

from instr_core.agent.parser import AgentParseError, parse_iv_sweep_goal


def test_parse_iv_sweep_goal_with_basic_units() -> None:
    result = parse_iv_sweep_goal(
        "Sweep 0V to 5V in 0.1V steps with 10mA compliance and 20ms delay"
    )

    assert result.start_voltage == 0
    assert result.stop_voltage == 5
    assert result.step == 0.1
    assert result.compliance == 0.01
    assert result.delay_ms == 20
    assert result.direction == "UP"


def test_parse_iv_sweep_goal_with_microamps_and_millivolts() -> None:
    result = parse_iv_sweep_goal(
        "Sweep 0 mV to 500 mV step 50 mV compliance 100 uA direction up"
    )

    assert result.start_voltage == 0
    assert result.stop_voltage == 0.5
    assert result.step == 0.05
    assert result.compliance == 100e-6
    assert result.direction == "UP"


def test_parse_iv_sweep_goal_rejects_missing_compliance() -> None:
    with pytest.raises(AgentParseError, match="compliance"):
        parse_iv_sweep_goal("Sweep 0V to 5V in 0.1V steps")


def test_parse_iv_sweep_goal_rejects_missing_step() -> None:
    with pytest.raises(AgentParseError, match="step"):
        parse_iv_sweep_goal("Sweep 0V to 5V with 10mA compliance")
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run:

```bash
uv run pytest tests/test_agent_parser.py -q
```

Expected: fail because `instr_core.agent.parser` does not exist.

- [ ] **Step 3: Implement models and parser**

Create `src/instr_core/agent/models.py`:

```python
"""Models for AI experiment-agent planning and execution."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from ..sweep import SweepConfig


class ExperimentType(str, Enum):
    """Supported agent experiment types."""

    IV_SWEEP = "iv_sweep"


class AgentPlanMode(str, Enum):
    """Execution mode for an agent plan."""

    DRY_RUN = "dry_run"
    EXECUTE = "execute"


class AgentRunStatus(str, Enum):
    """Lifecycle state for an agent run."""

    PLANNED = "planned"
    DRY_RUN = "dry_run"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ParsedIvSweepIntent(BaseModel):
    """Structured fields parsed from a natural-language IV sweep goal."""

    start_voltage: float
    stop_voltage: float
    step: float = Field(gt=0)
    compliance: float = Field(gt=0)
    delay_ms: int = Field(default=10, ge=0)
    direction: Literal["UP", "DOWN", "BOTH"] = "UP"

    def to_sweep_config(self) -> SweepConfig:
        """Convert parsed intent into the existing sweep config model."""
        return SweepConfig(
            start_voltage=self.start_voltage,
            stop_voltage=self.stop_voltage,
            step=self.step,
            compliance=self.compliance,
            delay_ms=self.delay_ms,
            direction=self.direction,
        )


class AgentPlan(BaseModel):
    """A structured experiment plan created by the agent layer."""

    plan_id: str
    experiment_type: ExperimentType = ExperimentType.IV_SWEEP
    mode: AgentPlanMode = AgentPlanMode.DRY_RUN
    goal: str
    instrument_key: str
    address: str
    config: SweepConfig
    commands: list[str]
    requires_confirmation: bool = True


class AgentValidationResult(BaseModel):
    """Validation result for an agent dry-run."""

    valid: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    estimated_points: int
    requires_confirmation: bool = True


class AgentRun(BaseModel):
    """Stored lifecycle state for an agent plan/run."""

    run_id: str
    plan: AgentPlan
    validation: AgentValidationResult | None = None
    status: AgentRunStatus = AgentRunStatus.PLANNED
    sweep_session_id: str | None = None
    error_message: str | None = None


class AgentPlanRequest(BaseModel):
    """Request to create an agent plan from natural language."""

    goal: str
    instrument_key: str | None = None
    address: str | None = None


class AgentPlanResponse(BaseModel):
    """Response containing a planned agent run."""

    run: AgentRun


class AgentDryRunRequest(BaseModel):
    """Request to dry-run an existing plan."""

    run_id: str


class AgentDryRunResponse(BaseModel):
    """Response containing dry-run validation."""

    run: AgentRun


class AgentExecuteRequest(BaseModel):
    """Request to execute a validated plan."""

    run_id: str
    confirm: bool = False


class AgentExecuteResponse(BaseModel):
    """Response after starting execution."""

    run: AgentRun
```

Create `src/instr_core/agent/parser.py`:

```python
"""Deterministic natural-language parser for the first agent workflows."""

from __future__ import annotations

import re

from .models import ParsedIvSweepIntent


class AgentParseError(ValueError):
    """Raised when a natural-language goal cannot be parsed safely."""


_NUMBER_UNIT = r"([-+]?\d+(?:\.\d+)?)\s*(mV|V|uA|µA|mA|A|ms|s)\b"


def _unit_value(number: str, unit: str) -> float:
    value = float(number)
    normalized = unit.lower().replace("µ", "u")
    if normalized == "v":
        return value
    if normalized == "mv":
        return value / 1000.0
    if normalized == "a":
        return value
    if normalized == "ma":
        return value / 1000.0
    if normalized == "ua":
        return value / 1_000_000.0
    if normalized == "s":
        return value * 1000.0
    if normalized == "ms":
        return value
    raise AgentParseError(f"Unsupported unit: {unit}")


def _extract_voltage_range(text: str) -> tuple[float | None, float | None]:
    match = re.search(
        rf"(?:sweep|scan|from)?\s*{_NUMBER_UNIT}\s*(?:to|->|through)\s*{_NUMBER_UNIT}",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None

    start_num, start_unit, stop_num, stop_unit = match.groups()
    if "a" in start_unit.lower() or "a" in stop_unit.lower():
        return None, None
    return _unit_value(start_num, start_unit), _unit_value(stop_num, stop_unit)


def _extract_step(text: str) -> float | None:
    match = re.search(
        rf"(?:step|steps|in)\s+{_NUMBER_UNIT}(?:\s*(?:step|steps))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    number, unit = match.groups()
    if "a" in unit.lower() or unit.lower() in ("ms", "s"):
        return None
    return _unit_value(number, unit)


def _extract_compliance(text: str) -> float | None:
    match = re.search(
        rf"(?:compliance|limit|current limit)\s*(?:of|at|=|:)?\s*{_NUMBER_UNIT}",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf"{_NUMBER_UNIT}\s*(?:compliance|current limit)",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    number, unit = match.groups()
    if "v" in unit.lower() or unit.lower() in ("ms", "s"):
        return None
    return _unit_value(number, unit)


def _extract_delay_ms(text: str) -> int:
    match = re.search(
        rf"(?:delay|settle|settling)\s*(?:of|=|:)?\s*{_NUMBER_UNIT}",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return 10
    number, unit = match.groups()
    if unit.lower() not in ("ms", "s"):
        return 10
    return int(round(_unit_value(number, unit)))


def _extract_direction(text: str) -> str:
    lowered = text.lower()
    if "both" in lowered or "up and down" in lowered or "round trip" in lowered:
        return "BOTH"
    if "down" in lowered and "direction" in lowered:
        return "DOWN"
    return "UP"


def parse_iv_sweep_goal(goal: str) -> ParsedIvSweepIntent:
    """Parse a natural-language IV sweep goal into structured values."""
    start, stop = _extract_voltage_range(goal)
    step = _extract_step(goal)
    compliance = _extract_compliance(goal)

    missing: list[str] = []
    if start is None:
        missing.append("start voltage")
    if stop is None:
        missing.append("stop voltage")
    if step is None:
        missing.append("step")
    if compliance is None:
        missing.append("compliance")
    if missing:
        raise AgentParseError(
            "Could not safely parse required IV sweep field(s): " + ", ".join(missing)
        )

    return ParsedIvSweepIntent(
        start_voltage=start,
        stop_voltage=stop,
        step=step,
        compliance=compliance,
        delay_ms=_extract_delay_ms(goal),
        direction=_extract_direction(goal),
    )
```

Create `src/instr_core/agent/__init__.py`:

```python
"""AI experiment-agent planning primitives."""

from .models import (
    AgentDryRunRequest,
    AgentDryRunResponse,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentPlan,
    AgentPlanRequest,
    AgentPlanResponse,
    AgentRun,
    AgentRunStatus,
    AgentValidationResult,
)
from .parser import AgentParseError, parse_iv_sweep_goal

__all__ = [
    "AgentDryRunRequest",
    "AgentDryRunResponse",
    "AgentExecuteRequest",
    "AgentExecuteResponse",
    "AgentParseError",
    "AgentPlan",
    "AgentPlanRequest",
    "AgentPlanResponse",
    "AgentRun",
    "AgentRunStatus",
    "AgentValidationResult",
    "parse_iv_sweep_goal",
]
```

- [ ] **Step 4: Run parser tests and verify they pass**

Run:

```bash
uv run pytest tests/test_agent_parser.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/instr_core/agent tests/test_agent_parser.py
git commit -m "feat: add IV sweep agent parser"
```

## Task 2: Planner, Dry-Run Validation, and Store

**Files:**
- Create: `src/instr_core/agent/planner.py`
- Create: `src/instr_core/agent/store.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write API tests for planning and dry-run**

Create `tests/test_agent_api.py` with fixtures matching existing API tests:

```python
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from instr_core.agent.store import AgentRunStore
from instr_core.api_server import create_api_app
from instr_core.sweep import SweepEngine
from instr_core.validator import Registry

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"


class MockResource:
    def __init__(self, idn_response: str = "KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1,1.0") -> None:
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
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
uv run pytest tests/test_agent_api.py -q
```

Expected: fail because planner, store, and routes do not exist.

- [ ] **Step 3: Implement store**

Create `src/instr_core/agent/store.py`:

```python
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
```

- [ ] **Step 4: Implement planner**

Create `src/instr_core/agent/planner.py`:

```python
"""Plan creation and validation for AI IV sweep agent workflows."""

from __future__ import annotations

import uuid

from ..api.services.sweep_service import validate_sweep_config
from ..schema import InstrumentSchema
from ..sweep import SweepConfig
from ..validator import Registry, validate_command
from .models import AgentPlan, AgentRun, AgentRunStatus, AgentValidationResult
from .parser import parse_iv_sweep_goal


def build_command_preview(config: SweepConfig) -> list[str]:
    """Build the deterministic command preview for an IV sweep."""
    max_voltage = max(abs(config.start_voltage), abs(config.stop_voltage))
    return [
        "*RST",
        ":OUTP OFF",
        ":SOUR:FUNC VOLT",
        f":SENS:CURR:PROT {config.compliance:g}",
        f":SOUR:VOLT:RANG {max_voltage:g}",
        f":SOUR:VOLT {config.start_voltage:g}",
        ":OUTP ON",
        "... sweep loop: :SOUR:VOLT <point>; :READ? ...",
        ":OUTP OFF",
    ]


def estimate_points(config: SweepConfig) -> int:
    """Return the number of sweep points for a config."""
    n_steps = int(round(abs(config.stop_voltage - config.start_voltage) / config.step))
    points = n_steps + 1
    if config.direction == "BOTH":
        return points * 2 - 1
    return points


def create_iv_sweep_run(
    goal: str,
    instrument_key: str,
    address: str,
) -> AgentRun:
    """Create a planned IV sweep run from natural language."""
    parsed = parse_iv_sweep_goal(goal)
    config = parsed.to_sweep_config()
    plan = AgentPlan(
        plan_id=f"plan-{uuid.uuid4().hex[:8]}",
        goal=goal,
        instrument_key=instrument_key,
        address=address,
        config=config,
        commands=build_command_preview(config),
    )
    return AgentRun(run_id=f"run-{uuid.uuid4().hex[:8]}", plan=plan)


def dry_run_plan(run: AgentRun, registry: Registry) -> AgentRun:
    """Validate a planned run without touching VISA."""
    issues: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []
    schema: InstrumentSchema | None = registry.try_get_schema(run.plan.instrument_key)

    if schema is None:
        issues.append(f"Instrument '{run.plan.instrument_key}' not found in registry")
    else:
        try:
            validate_sweep_config(run.plan.config, schema)
        except ValueError as exc:
            issues.append(str(exc))

        state: dict[str, str] = {}
        for raw in run.plan.commands:
            if raw.startswith("..."):
                continue
            command, argument = _split_preview_command(raw)
            result = validate_command(schema, command, argument, state)
            if not result.valid and not raw.endswith("?"):
                issues.extend(result.issues)
                suggestions.extend(result.suggestions)
            _apply_preview_state(command, argument, state)

    validation = AgentValidationResult(
        valid=not issues,
        issues=issues,
        warnings=warnings,
        suggestions=suggestions,
        commands=run.plan.commands,
        estimated_points=estimate_points(run.plan.config),
        requires_confirmation=True,
    )
    run.validation = validation
    run.status = AgentRunStatus.DRY_RUN
    return run


def ensure_executable(run: AgentRun, confirm: bool) -> None:
    """Raise ValueError unless a run is ready for real execution."""
    if not confirm:
        raise ValueError("Execution requires confirm=true")
    if run.validation is None:
        raise ValueError("Run must be dry-run before execution")
    if not run.validation.valid:
        raise ValueError("Cannot execute an invalid dry-run")


def _split_preview_command(raw: str) -> tuple[str, str | None]:
    if " " in raw:
        command, argument = raw.split(" ", 1)
        return command.strip(), argument.strip()
    return raw.strip(), None


def _apply_preview_state(command: str, argument: str | None, state: dict[str, str]) -> None:
    if command == ":SOUR:FUNC" and argument is not None:
        state["source_mode"] = argument
    elif command == ":SENS:CURR:PROT" and argument is not None:
        state[":SENS:CURR:PROT"] = argument
    elif command == ":SOUR:VOLT" and argument is not None:
        state[":SOUR:VOLT"] = argument
    elif command == ":OUTP" and argument is not None:
        state["output"] = argument
```

- [ ] **Step 5: Run API tests and verify they still fail on missing routes**

Run:

```bash
uv run pytest tests/test_agent_api.py -q
```

Expected: fail with 404 for `/agent/plan`.

## Task 3: FastAPI Agent Routes

**Files:**
- Create: `src/instr_core/api/routes/agent.py`
- Modify: `src/instr_core/api/routes/__init__.py`
- Modify: `src/instr_core/api_server.py`
- Modify: `src/instr_core/api/dependencies.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Add app state dependency**

Modify `src/instr_core/api/dependencies.py`:

```python
from ..agent.store import AgentRunStore
```

In `init_app_state`, after `app.state.sweep_engine = SweepEngine()`:

```python
    app.state.agent_store = AgentRunStore()
    logger.info("AgentRunStore initialized")
```

Add:

```python
def get_agent_store(request: Request) -> AgentRunStore:
    """FastAPI dependency: get the agent run store."""
    return request.app.state.agent_store
```

- [ ] **Step 2: Implement agent route**

Create `src/instr_core/api/routes/agent.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...agent import (
    AgentDryRunRequest,
    AgentDryRunResponse,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentParseError,
    AgentPlanRequest,
    AgentPlanResponse,
    AgentRunStatus,
)
from ...agent.planner import create_iv_sweep_run, dry_run_plan, ensure_executable
from ...agent.store import AgentRunStore
from ...sweep import SweepSession, SweepStatus
from ..dependencies import _get_address_schema, get_agent_store, get_registry, get_sweep_engine
from ..services.visa_service import get_visa

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/plan", response_model=AgentPlanResponse)
def create_plan(
    req: AgentPlanRequest,
    request: Request,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
) -> AgentPlanResponse:
    """Create an IV sweep agent plan from natural language."""
    address = req.address
    if address is None:
        raise HTTPException(status_code=400, detail="address is required for IV sweep planning")

    instrument_key = req.instrument_key or _get_address_schema(request, address)
    if instrument_key is None:
        raise HTTPException(
            status_code=400,
            detail="address is not connected to a known instrument schema",
        )
    if registry.try_get_schema(instrument_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument '{instrument_key}' not found in registry",
        )

    try:
        run = create_iv_sweep_run(req.goal, instrument_key, address)
    except AgentParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    store.create(run)
    return AgentPlanResponse(run=run)


@router.post("/dry-run", response_model=AgentDryRunResponse)
def dry_run(
    req: AgentDryRunRequest,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
) -> AgentDryRunResponse:
    """Validate an agent plan without touching VISA."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")
    run = dry_run_plan(run, registry)
    store.update(run)
    return AgentDryRunResponse(run=run)


@router.post("/execute", response_model=AgentExecuteResponse)
def execute(
    req: AgentExecuteRequest,
    store: AgentRunStore = Depends(get_agent_store),
    registry=Depends(get_registry),
    sweep_engine=Depends(get_sweep_engine),
) -> AgentExecuteResponse:
    """Execute a validated agent plan after explicit confirmation."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")

    try:
        ensure_executable(run, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        visa_resource = get_visa().open_resource(run.plan.address)
        session = SweepSession(
            session_id=f"swp-{run.run_id.removeprefix('run-')}",
            instrument_key=run.plan.instrument_key,
            address=run.plan.address,
            config=run.plan.config,
            status=SweepStatus.IDLE,
        )
        sweep_engine.start_sweep(session, registry, visa_resource)
    except Exception as exc:
        run.status = AgentRunStatus.FAILED
        run.error_message = str(exc)
        store.update(run)
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}")

    run.status = AgentRunStatus.RUNNING
    run.sweep_session_id = session.session_id
    store.update(run)
    return AgentExecuteResponse(run=run)


@router.get("/runs/{run_id}", response_model=AgentPlanResponse)
def get_run(
    run_id: str,
    store: AgentRunStore = Depends(get_agent_store),
) -> AgentPlanResponse:
    """Return a stored agent run."""
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return AgentPlanResponse(run=run)
```

- [ ] **Step 3: Register route**

Modify `src/instr_core/api/routes/__init__.py`:

```python
from .agent import router as agent_router
from .instruments import router as instruments_router
from .sweep import router as sweep_router
from .validate import router as validate_router
from .visa import router as visa_router

__all__ = [
    "agent_router",
    "instruments_router",
    "sweep_router",
    "validate_router",
    "visa_router",
]
```

Modify `src/instr_core/api_server.py` route imports and registration:

```python
from .api.routes import agent_router, instruments_router, sweep_router, validate_router, visa_router
```

Then include:

```python
    app.include_router(agent_router)
```

- [ ] **Step 4: Run agent API tests**

Run:

```bash
uv run pytest tests/test_agent_api.py -q
```

Expected: planning and dry-run tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/instr_core/agent src/instr_core/api tests/test_agent_api.py
git commit -m "feat: add IV sweep agent API"
```

## Task 4: Execute Endpoint Tests and Final Verification

**Files:**
- Modify: `tests/test_agent_api.py`
- Modify: implementation files only if tests expose gaps

- [ ] **Step 1: Add execute tests**

Append to `tests/test_agent_api.py`:

```python
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
    )

    assert execute_response.status_code == 200
    run = execute_response.json()["run"]
    assert run["status"] == "running"
    assert run["sweep_session_id"] is not None
```

- [ ] **Step 2: Run execute tests**

Run:

```bash
uv run pytest tests/test_agent_api.py -q
```

Expected: all agent API tests pass.

- [ ] **Step 3: Run full Python verification**

Run:

```bash
uv run ruff check .
uv run mypy src/instr_core
uv run pytest tests/ -q
```

Expected:

- ruff: `All checks passed!`
- mypy: `Success: no issues found`
- pytest: all tests pass

- [ ] **Step 4: Run desktop/Rust smoke checks**

Run:

```bash
cd desktop && npm run build
cd src-tauri && cargo check
```

Expected:

- TypeScript/Vite build passes.
- Cargo check finishes successfully.

- [ ] **Step 5: Commit final verification changes**

Run:

```bash
git status --short
git add .
git commit -m "test: cover IV sweep agent execution"
```

## Self-Review

- Spec coverage: The plan covers rule-based parsing, plan creation, dry-run validation, confirmed execute, run lookup, API routes, and tests. It intentionally excludes LLM and desktop chat UI per spec.
- Placeholder scan: No unresolved placeholder markers are present.
- Type consistency: `AgentPlan`, `AgentRun`, `AgentValidationResult`, route request/response names, and store method names are consistent across tasks.
