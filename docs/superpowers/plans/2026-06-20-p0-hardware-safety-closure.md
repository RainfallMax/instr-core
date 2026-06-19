# P0 Hardware Safety Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every hardware write fail closed, validate before VISA access, reuse a typed emergency teardown path, prevent concurrent address ownership, and expose a global emergency stop.

**Architecture:** Add a pure command-preflight service between HTTP parsing and VISA access. Extract output shutdown into a reusable typed service used by sweep engines and multi-instrument execution. Add an application-scoped ownership registry that gates hardware runs and provides the active-resource set for emergency stop.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, PyVISA compatibility layer, pytest, Ruff, Mypy

---

## File Structure

- Create `src/instr_core/api/services/command_preflight.py` — pure command classification and validation with no VISA access.
- Create `src/instr_core/api/services/safety_service.py` — typed emergency teardown report and retry/fallback logic.
- Create `src/instr_core/api/services/ownership_service.py` — thread-safe address ownership registry.
- Modify `src/instr_core/api/routes/validate.py` — address-aware fail-closed standalone validation.
- Modify `src/instr_core/api/routes/visa.py` — run preflight before `get_visa()` and block validation bypass.
- Modify `src/instr_core/api/routes/sweep.py` — acquire/release address ownership.
- Modify `src/instr_core/api/routes/agent.py` — acquire/release ownership for agent execution and add emergency-stop route.
- Modify `src/instr_core/api/dependencies.py` — initialize and expose ownership state.
- Modify `src/instr_core/sweep/engine.py` — delegate output shutdown to the shared safety service.
- Modify `src/instr_core/agent/planner.py` — use shared teardown and preserve execution errors.
- Modify `src/instr_core/api/models.py` — add typed preflight/teardown/emergency-stop response models where API-visible.
- Modify `tests/test_api_server.py` — fail-closed and ordering regression tests.
- Modify `tests/test_sweep_engine.py` — shared teardown integration tests.
- Modify `tests/test_agent_multi_api.py` — dual-device teardown and ownership tests.
- Create `tests/test_safety_service.py` — focused teardown service tests.
- Create `tests/test_ownership_service.py` — focused ownership concurrency tests.
- Modify `README.md`, `README_zh-CN.md`, and `docs/PRD_IVSWEEP.md` — document fail-closed behavior.

### Task 1: Fail Closed in Standalone Validation

**Files:**
- Modify: `tests/test_api_server.py`
- Modify: `src/instr_core/api/routes/validate.py`
- Modify: `README.md`
- Modify: `README_zh-CN.md`

- [ ] **Step 1: Change the no-schema test to require rejection**

Replace the existing soft-pass test with:

```python
def test_no_schema_fails_closed(self, client: TestClient) -> None:
    res = client.post(
        "/validate/command",
        json={"command": ":SOUR:VOLT 10"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False
    assert any("No schema available" in issue for issue in data["issues"])
    assert any("provide explicit instrument" in item.lower() for item in data["suggestions"])
```

- [ ] **Step 2: Add address-based schema resolution coverage**

Add:

```python
def test_address_resolves_connected_schema(self, client: TestClient) -> None:
    client.app.state.address_to_schema["USB0::KNOWN::INSTR"] = "keithley/smu/2600"
    res = client.post(
        "/validate/command",
        json={
            "address": "USB0::KNOWN::INSTR",
            "command": ":SOUR:FUNC VOLT",
            "current_state": {"output": "OFF"},
        },
    )
    assert res.status_code == 200
    assert res.json()["valid"] is True
    assert res.json()["instrument"] == "keithley/smu/2600"
```

- [ ] **Step 3: Run the tests and verify the intended failures**

Run:

```bash
uv run pytest tests/test_api_server.py::TestValidateCommand::test_no_schema_fails_closed tests/test_api_server.py::TestValidateCommand::test_address_resolves_connected_schema -v
```

Expected: the first test fails because `valid` is currently `True`; the second fails because address lookup is not implemented.

- [ ] **Step 4: Implement request-aware schema resolution**

Change the route signature to receive `Request`, resolve `_get_address_schema`
when `instrument` is absent and `address` is present, and return:

```python
return ValidateResponse(
    instrument=None,
    address=req.address,
    command=req.command,
    argument=req.argument,
    valid=False,
    issues=["No schema available for validation"],
    suggestions=["Connect the instrument or provide explicit instrument key"],
)
```

The explicit `instrument` field continues to take precedence over the address mapping.

- [ ] **Step 5: Run focused validation tests**

Run:

```bash
uv run pytest tests/test_api_server.py::TestValidateCommand -v
```

Expected: all validation endpoint tests pass.

- [ ] **Step 6: Update user documentation**

Replace statements that describe no-schema validation as a permissive fallback
with the invariant that unverifiable writes are rejected and users must connect
a recognized instrument or provide a schema key.

- [ ] **Step 7: Commit**

```bash
git add tests/test_api_server.py src/instr_core/api/routes/validate.py README.md README_zh-CN.md
git commit -m "fix: fail closed without validation schema"
```

### Task 2: Validate Before VISA Access

**Files:**
- Create: `src/instr_core/api/services/command_preflight.py`
- Modify: `src/instr_core/api/routes/visa.py`
- Modify: `tests/test_api_server.py`

- [ ] **Step 1: Add a regression test proving rejected writes never touch VISA**

Add:

```python
@patch("instr_core.api.routes.visa.get_visa")
def test_unknown_schema_write_is_rejected_before_visa(
    self, mock_get_visa: MagicMock, client: TestClient
) -> None:
    client.app.state.address_to_schema["USB0::UNKNOWN::INSTR"] = None
    res = client.post(
        "/visa/command",
        json={
            "address": "USB0::UNKNOWN::INSTR",
            "command": ":OUTP ON",
            "validate": True,
        },
    )
    assert res.status_code == 422
    assert "schema" in res.json()["detail"].lower()
    mock_get_visa.assert_not_called()
```

- [ ] **Step 2: Add validation-bypass rejection coverage**

Add:

```python
@patch("instr_core.api.routes.visa.get_visa")
def test_hardware_write_cannot_disable_validation(
    self, mock_get_visa: MagicMock, client: TestClient
) -> None:
    client.app.state.address_to_schema["USB0::KNOWN::INSTR"] = "keithley/smu/2600"
    res = client.post(
        "/visa/command",
        json={
            "address": "USB0::KNOWN::INSTR",
            "command": ":SOUR:VOLT 1",
            "validate": False,
        },
    )
    assert res.status_code == 422
    assert "validation" in res.json()["detail"].lower()
    mock_get_visa.assert_not_called()
```

- [ ] **Step 3: Add discovery-query allowlist coverage**

Add:

```python
@patch("instr_core.api_server.pyvisa")
def test_idn_query_is_allowed_without_schema(
    self, mock_pyvisa: MagicMock, client: TestClient
) -> None:
    mock_pyvisa.ResourceManager.return_value = MockResourceManager(
        idn_response="Unknown Corp,XYZ123,999,1.0"
    )
    client.app.state.address_to_schema["USB0::UNKNOWN::INSTR"] = None
    res = client.post(
        "/visa/command",
        json={
            "address": "USB0::UNKNOWN::INSTR",
            "command": "*IDN?",
            "validate": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["response"] == "Unknown Corp,XYZ123,999,1.0"
```

Also add a test showing an arbitrary unknown query such as `:READ?` returns
422 before VISA access.

- [ ] **Step 4: Run tests and verify they fail for the missing boundary**

Run:

```bash
uv run pytest tests/test_api_server.py::TestVisaCommand -v
```

Expected: unknown-schema writes and validation bypass currently reach VISA;
arbitrary queries are currently allowed.

- [ ] **Step 5: Implement pure preflight**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ...validator import Registry, validate_command
from ..dependencies import _get_address_schema, _get_address_state
from .visa_service import split_command_argument

DISCOVERY_QUERY_ALLOWLIST = frozenset({"*IDN?"})


@dataclass(frozen=True)
class CommandPreflight:
    command: str
    argument: str | None
    is_query: bool
    validated: bool
    issues: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()


class CommandRejected(ValueError):
    def __init__(self, message: str, issues: list[str], suggestions: list[str]) -> None:
        super().__init__(message)
        self.issues = issues
        self.suggestions = suggestions


def preflight_hardware_command(
    request: Request,
    address: str,
    raw_command: str,
    should_validate: bool,
    registry: Registry | None,
) -> CommandPreflight:
    command, argument = split_command_argument(raw_command)
    is_query = command.endswith("?")
    if not should_validate:
        raise CommandRejected(
            "Hardware command validation cannot be disabled",
            ["Validation bypass is not permitted"],
            ["Submit the command with validate=true"],
        )
    schema_key = _get_address_schema(request, address)
    if schema_key is None:
        if is_query and command.upper() in DISCOVERY_QUERY_ALLOWLIST:
            return CommandPreflight(command, argument, True, False)
        raise CommandRejected(
            "No schema available for hardware command",
            ["The connected address has no matched instrument schema"],
            ["Connect a recognized instrument before sending this command"],
        )
    if registry is None:
        raise CommandRejected(
            "Instrument registry is unavailable",
            ["The hardware command cannot be validated"],
            ["Configure the registry and retry"],
        )
    schema = registry.try_get_schema(schema_key)
    if schema is None:
        raise CommandRejected(
            f"Instrument schema '{schema_key}' is unavailable",
            ["The mapped schema could not be loaded"],
            ["Refresh the registry or reconnect the instrument"],
        )
    state = _get_address_state(request, address) or {}
    result = validate_command(schema, command, argument, state)
    if not result.valid:
        raise CommandRejected(
            "Hardware command failed validation",
            result.issues,
            result.suggestions,
        )
    return CommandPreflight(
        command,
        argument,
        is_query,
        True,
        tuple(result.issues),
        tuple(result.suggestions),
    )
```

- [ ] **Step 6: Call preflight before `get_visa()`**

In `send_command_endpoint`, call `preflight_hardware_command` first. Translate
`CommandRejected` to `HTTPException(status_code=422, detail=str(exc))`. Only
after successful preflight call `get_visa()` and `open_resource()`.

Use the preflight descriptor for query detection, response metadata, and state
updates. Remove the old permissive query/write branch.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/test_api_server.py::TestVisaCommand -v
```

Expected: all command boundary tests pass and mocked rejected cases prove no
VISA access.

- [ ] **Step 8: Commit**

```bash
git add src/instr_core/api/services/command_preflight.py src/instr_core/api/routes/visa.py tests/test_api_server.py
git commit -m "fix: validate commands before visa access"
```

### Task 3: Extract Typed Emergency Teardown

**Files:**
- Create: `src/instr_core/api/services/safety_service.py`
- Create: `tests/test_safety_service.py`
- Modify: `src/instr_core/sweep/engine.py`
- Modify: `tests/test_sweep_engine.py`

- [ ] **Step 1: Write focused teardown tests**

Create tests for:

```python
def test_teardown_succeeds_on_first_output_off() -> None: ...
def test_teardown_retries_output_off_once() -> None: ...
def test_teardown_uses_reset_after_two_failures() -> None: ...
def test_teardown_reports_critical_failure() -> None: ...
```

Each test asserts the exact command sequence and a returned report containing:
`safe`, `attempted_commands`, `successful_command`, and `errors`.

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```bash
uv run pytest tests/test_safety_service.py -v
```

Expected: collection fails because `safety_service` does not exist.

- [ ] **Step 3: Implement the typed service**

Create:

```python
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("instr_core.safety")


@dataclass(frozen=True)
class TeardownReport:
    safe: bool
    attempted_commands: tuple[str, ...]
    successful_command: str | None
    errors: tuple[str, ...]


def safe_turn_off_output(
    visa: Any,
    operation_id: str,
    address: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TeardownReport:
    attempted: list[str] = []
    errors: list[str] = []
    for index, command in enumerate((":OUTP OFF", ":OUTP OFF", "*RST")):
        attempted.append(command)
        try:
            visa.write(command)
            logger.info("%s: emergency command %s succeeded", operation_id, command)
            return TeardownReport(True, tuple(attempted), command, tuple(errors))
        except Exception as exc:
            errors.append(f"{command}: {exc}")
            logger.warning("%s: emergency command %s failed: %s", operation_id, command, exc)
            if index == 0:
                sleep(0.1)
    logger.critical(
        "%s: CRITICAL: Output may still be ON for %s",
        operation_id,
        address or "unknown address",
    )
    return TeardownReport(False, tuple(attempted), None, tuple(errors))
```

- [ ] **Step 4: Run focused service tests**

Run:

```bash
uv run pytest tests/test_safety_service.py -v
```

Expected: all teardown service tests pass.

- [ ] **Step 5: Delegate `SweepEngine` teardown**

Replace `_safe_turn_off_output` internals with a compatibility wrapper:

```python
@staticmethod
def _safe_turn_off_output(visa: Any, session_id: str) -> TeardownReport:
    return safe_turn_off_output(visa, session_id)
```

Keep existing tests and add an assertion that a report is returned.

- [ ] **Step 6: Run sweep tests**

Run:

```bash
uv run pytest tests/test_safety_service.py tests/test_sweep_engine.py -v
```

Expected: all service and sweep tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/instr_core/api/services/safety_service.py src/instr_core/sweep/engine.py tests/test_safety_service.py tests/test_sweep_engine.py
git commit -m "refactor: share typed emergency teardown"
```

### Task 4: Apply Safe Teardown to Dual-Instrument Execution

**Files:**
- Modify: `src/instr_core/agent/planner.py`
- Modify: `src/instr_core/api/routes/agent.py`
- Modify: `tests/test_agent_multi_api.py`

- [ ] **Step 1: Add a failure resource that rejects output-off**

Add a mock source resource whose measurement loop fails and whose first two
`:OUTP OFF` writes fail. Record all attempted commands.

- [ ] **Step 2: Add an API regression test**

Add a test that plans, dry-runs, and executes the dual workflow, then asserts:

```python
assert execute_response.status_code == 500
stored = client.get(f"/agent/multi/runs/{run_id}").json()["run"]
assert stored["status"] == "failed"
assert "measurement failed" in stored["error_message"]
assert source.attempted_shutdown == [":OUTP OFF", ":OUTP OFF", "*RST"]
```

- [ ] **Step 3: Run the test and verify current unsafe failure**

Run the new test directly. Expected: current `finally: source.write(":OUTP OFF")`
replaces the original error and does not retry or reset.

- [ ] **Step 4: Use shared teardown without masking the original error**

Structure execution as:

```python
execution_error: Exception | None = None
try:
    ...
except Exception as exc:
    execution_error = exc
finally:
    teardown = safe_turn_off_output(
        source,
        run.run_id,
        run.plan.source.address,
    )

if execution_error is not None:
    raise execution_error
if not teardown.safe:
    raise RuntimeError("Sweep completed but source output could not be confirmed off")
```

Do not mark the run completed until teardown is safe.

- [ ] **Step 5: Run dual-agent tests**

Run:

```bash
uv run pytest tests/test_agent_multi_api.py -v
```

Expected: all multi-agent tests pass, including preservation of the original
execution failure.

- [ ] **Step 6: Commit**

```bash
git add src/instr_core/agent/planner.py src/instr_core/api/routes/agent.py tests/test_agent_multi_api.py
git commit -m "fix: harden dual-instrument teardown"
```

### Task 5: Add Address Ownership

**Files:**
- Create: `src/instr_core/api/services/ownership_service.py`
- Create: `tests/test_ownership_service.py`
- Modify: `src/instr_core/api/dependencies.py`
- Modify: `src/instr_core/api/routes/sweep.py`
- Modify: `src/instr_core/api/routes/agent.py`
- Modify: `tests/test_api_server.py`
- Modify: `tests/test_agent_multi_api.py`

- [ ] **Step 1: Write ownership service tests**

Cover:

```python
def test_acquire_and_release_address() -> None: ...
def test_second_owner_is_rejected() -> None: ...
def test_same_owner_can_release_only_its_address() -> None: ...
def test_concurrent_acquire_has_one_winner() -> None: ...
```

- [ ] **Step 2: Verify tests fail because the service is absent**

Run:

```bash
uv run pytest tests/test_ownership_service.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement ownership registry**

Create an `AddressOwnershipRegistry` with an internal `RLock`, `acquire`,
`acquire_many`, `release`, `release_many`, and `snapshot`. `acquire_many`
checks all addresses before mutating so partial acquisition cannot occur.

- [ ] **Step 4: Initialize ownership in app state**

Set `app.state.address_ownership = AddressOwnershipRegistry()` in
`init_app_state` and add `get_address_ownership`.

- [ ] **Step 5: Add API conflict tests**

Seed ownership in tests and assert:

- `/sweep/start` returns 409 without opening VISA when the address is owned.
- `/agent/multi/execute` returns 409 without opening either VISA resource when
  either source or meter is owned.
- Ownership is released after completion and after error teardown.

- [ ] **Step 6: Run tests and verify conflict cases fail**

Run:

```bash
uv run pytest tests/test_ownership_service.py tests/test_api_server.py tests/test_agent_multi_api.py -v
```

Expected: service tests pass after implementation; API conflict cases fail until
routes use the registry.

- [ ] **Step 7: Gate execution routes**

Acquire all required addresses before VISA access. Return HTTP 409 when
acquisition fails. Release ownership from execution completion/error callbacks;
for synchronous dual execution, use `finally`. For background sweeps, add a
completion callback to `SweepEngine.start_sweep`.

- [ ] **Step 8: Run focused ownership tests**

Run:

```bash
uv run pytest tests/test_ownership_service.py tests/test_api_server.py tests/test_agent_multi_api.py -v
```

Expected: all ownership and affected API tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/instr_core/api/services/ownership_service.py src/instr_core/api/dependencies.py src/instr_core/api/routes/sweep.py src/instr_core/api/routes/agent.py tests/test_ownership_service.py tests/test_api_server.py tests/test_agent_multi_api.py
git commit -m "feat: prevent concurrent instrument ownership"
```

### Task 6: Add Global Emergency Stop

**Files:**
- Modify: `src/instr_core/api/models.py`
- Modify: `src/instr_core/api/routes/visa.py`
- Modify: `src/instr_core/api/services/ownership_service.py`
- Modify: `tests/test_api_server.py`
- Modify: `desktop/src/types.ts`
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/i18n.ts`
- Modify: `desktop/src/App.css`

- [ ] **Step 1: Add backend emergency-stop API tests**

Create two owned mock resources and assert `POST /visa/emergency-stop`:

- calls teardown for each owned output address;
- returns one typed result per address;
- reports HTTP 200 even when one device cannot confirm shutdown;
- includes `all_safe=false` for partial failure;
- releases only addresses whose teardown was confirmed safe.

- [ ] **Step 2: Run the tests and verify 404**

Run the new tests directly. Expected: 404 because the endpoint is absent.

- [ ] **Step 3: Add typed response models**

Add Pydantic models:

```python
class EmergencyStopResult(BaseModel):
    address: str
    operation_id: str
    safe: bool
    attempted_commands: list[str]
    successful_command: str | None
    errors: list[str]


class EmergencyStopResponse(BaseModel):
    all_safe: bool
    results: list[EmergencyStopResult]
```

- [ ] **Step 4: Implement emergency-stop endpoint**

Snapshot ownership, open each owned resource, invoke `safe_turn_off_output`,
collect all results, and continue after per-device errors. Release safe
addresses. Never raise before all addresses have been attempted.

- [ ] **Step 5: Run backend tests**

Run:

```bash
uv run pytest tests/test_api_server.py -v
```

Expected: all API tests pass.

- [ ] **Step 6: Add desktop Emergency Stop**

Add a persistent red Emergency Stop button to the application header. It calls
`POST /visa/emergency-stop`, disables while pending, and displays a success or
critical partial-failure message. Add English and Chinese translations and
typed response interfaces.

- [ ] **Step 7: Run frontend build**

Run:

```bash
cd desktop && npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 8: Commit**

```bash
git add src/instr_core/api/models.py src/instr_core/api/routes/visa.py src/instr_core/api/services/ownership_service.py tests/test_api_server.py desktop/src/types.ts desktop/src/App.tsx desktop/src/i18n.ts desktop/src/App.css
git commit -m "feat: add global emergency stop"
```

### Task 7: Documentation and Full Verification

**Files:**
- Modify: `docs/PRD_IVSWEEP.md`
- Modify: `docs/PRD_SECURITY_FIX_001.md`
- Modify: `docs/superpowers/plans/2026-06-20-p0-hardware-safety-closure.md`

- [ ] **Step 1: Correct permissive no-schema documentation**

Change IV sweep behavior from “allow without validation” to “reject start until
a trusted schema is matched.”

- [ ] **Step 2: Record implementation evidence**

Check completed task boxes and append the exact focused verification output and
mock-only hardware qualification note. Do not claim real-device qualification.

- [ ] **Step 3: Run Python quality gates**

Run:

```bash
uv run ruff check src tests
uv run mypy src
uv run pytest tests/ -v
```

Expected: zero Ruff errors, zero Mypy errors, all tests pass.

- [ ] **Step 4: Run desktop and Rust quality gates**

Run:

```bash
cd desktop && npm run build
cd desktop/src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test
```

Expected: frontend build and all Rust checks pass.

- [ ] **Step 5: Audit P0 invariants**

Verify with source inspection and tests:

- unknown-schema writes cannot reach VISA;
- validation cannot be disabled;
- only allowlisted discovery queries bypass schema validation;
- standalone validation never soft-passes;
- single and dual sweeps use the same teardown service;
- owned addresses reject concurrent execution;
- emergency stop attempts every active address.

- [ ] **Step 6: Commit final P0 evidence**

```bash
git add docs/PRD_IVSWEEP.md docs/PRD_SECURITY_FIX_001.md docs/superpowers/plans/2026-06-20-p0-hardware-safety-closure.md
git commit -m "docs: record p0 safety closure"
```
