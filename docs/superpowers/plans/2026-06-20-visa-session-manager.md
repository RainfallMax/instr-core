# VISA Session Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace direct VISA resource opening with reusable, locked, observable managed sessions across REST, sweeps, agents, emergency stop, desktop state, and application shutdown.

**Architecture:** A `VisaSessionManager` owns one resource per connected address and exposes context-managed leases protected by per-address locks. Routes resolve identity and schema during atomic connect, while all hardware consumers borrow existing sessions and never create unmanaged resources.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, PyVISA compatibility layer, React 18, TypeScript, pytest, Ruff, Mypy

---

## File Map

- Create `src/instr_core/api/services/session_manager.py` — managed session model, errors, leases, lifecycle.
- Create `tests/test_session_manager.py` — unit and concurrency tests.
- Modify `src/instr_core/api/dependencies.py` — initialize and provide manager; clear address mappings.
- Modify `src/instr_core/api/models.py` — additive connection health metadata.
- Modify `src/instr_core/api/routes/visa.py` — connect/list/disconnect/reconnect and managed commands/emergency stop.
- Modify `src/instr_core/api/routes/sweep.py` — borrow managed session lease.
- Modify `src/instr_core/api/routes/agent.py` — single and dual managed leases.
- Modify `src/instr_core/agent/planner.py` — execute dual workflow with already-borrowed resources.
- Modify `src/instr_core/api_server.py` — deterministic shutdown.
- Modify API and agent tests to seed sessions rather than address mappings alone.
- Modify desktop connection state and Connected panel for hydration/disconnect.

### Task 1: Implement the Session Manager Core

**Files:**
- Create: `tests/test_session_manager.py`
- Create: `src/instr_core/api/services/session_manager.py`

- [ ] **Step 1: Write failing manager tests**

Cover successful connect, idempotent duplicate connect, failed identify cleanup,
concurrent duplicate connect, lease serialization, I/O health marking,
disconnect, reconnect, and shutdown.

The basic test API is:

```python
manager = VisaSessionManager(lambda: resource_manager)
session = manager.connect("USB0::1", identify)
with manager.lease("USB0::1") as resource:
    resource.write("*CLS")
manager.disconnect("USB0::1")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_session_manager.py -v
```

Expected: import failure because the manager does not exist.

- [ ] **Step 3: Implement typed session lifecycle**

Implement:

```python
class SessionNotFound(LookupError): ...
class SessionUnhealthy(RuntimeError): ...
class SessionConnectError(RuntimeError): ...
class SessionCloseError(RuntimeError): ...

@dataclass
class ManagedVisaSession:
    address: str
    resource: Any
    instrument: ConnectedInstrument
    connected_at: str
    healthy: bool = True
    last_error: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
```

`VisaSessionManager` uses an `RLock`, publishes only fully identified sessions,
closes duplicate concurrent resources, and performs no hardware I/O while
holding its registry lock.

- [ ] **Step 4: Verify GREEN and quality**

Run:

```bash
uv run pytest tests/test_session_manager.py -v
uv run ruff check src/instr_core/api/services/session_manager.py tests/test_session_manager.py
uv run mypy src/instr_core/api/services/session_manager.py
```

- [ ] **Step 5: Commit**

```bash
git add src/instr_core/api/services/session_manager.py tests/test_session_manager.py
git commit -m "feat: add managed visa sessions"
```

### Task 2: Integrate Connect, Connected, Disconnect, and Reconnect

**Files:**
- Modify: `tests/test_api_server.py`
- Modify: `src/instr_core/api/dependencies.py`
- Modify: `src/instr_core/api/models.py`
- Modify: `src/instr_core/api/routes/visa.py`

- [ ] **Step 1: Add failing API lifecycle tests**

Prove:

- repeated connect opens and identifies once;
- `/visa/connected` returns the real session;
- failed identification closes the temporary resource and leaves no session;
- disconnect closes and clears schema/state;
- disconnect/reconnect return 409 while ownership is active;
- reconnect opens a fresh resource;
- disconnected commands return 409 without `open_resource`.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_api_server.py -v
```

Expected: new lifecycle tests fail against current direct-resource routes.

- [ ] **Step 3: Initialize and expose the manager**

Add `get_visa_sessions(request)` and initialize:

```python
app.state.visa_sessions = VisaSessionManager(get_visa)
```

Add `_clear_address_tracking(request, address)` to atomically remove schema and
virtual state after disconnect.

- [ ] **Step 4: Extend connection response metadata**

Add optional `connected_at`, `healthy`, and `last_error` fields to
`ConnectedInstrument` so existing clients remain compatible.

- [ ] **Step 5: Refactor VISA routes**

Use `manager.connect` with an identity callback that parses `*IDN?` and resolves
the Registry. Implement real connected list, disconnect, and reconnect.
Translate manager errors to 404, 409, or 500 as specified.

- [ ] **Step 6: Use managed lease for commands and emergency stop**

Preflight remains before lease acquisition. Replace every direct
`open_resource` in `visa.py` with `manager.lease(address)`.

- [ ] **Step 7: Verify and commit**

Run:

```bash
uv run pytest tests/test_api_server.py tests/test_session_manager.py -v
uv run ruff check src tests
uv run mypy src
```

Then:

```bash
git add src/instr_core/api/dependencies.py src/instr_core/api/models.py src/instr_core/api/routes/visa.py tests/test_api_server.py
git commit -m "feat: manage visa connection lifecycle"
```

### Task 3: Integrate Sweeps and Single-Device Agents

**Files:**
- Modify: `tests/test_api_server.py`
- Modify: `tests/test_agent_api.py`
- Modify: `src/instr_core/api/routes/sweep.py`
- Modify: `src/instr_core/api/routes/agent.py`

- [ ] **Step 1: Add failing managed-session execution tests**

Assert sweep and agent execution:

- fail with 409 when address is not connected;
- reuse the resource opened by `/visa/connect`;
- do not call `ResourceManager.open_resource` during execution;
- retain the connected session after completion;
- mark the session unhealthy on VISA I/O failure.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_api_server.py tests/test_agent_api.py -v
```

- [ ] **Step 3: Borrow a session lease for background sweeps**

Add a lease object that may be entered before thread start and released from
the sweep completion callback. Do not allow disconnect while ownership is
active.

- [ ] **Step 4: Refactor route consumers**

Remove direct `get_visa().open_resource` calls from sweep and single-agent
routes. Preserve ownership release on all startup failures.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_api_server.py tests/test_agent_api.py tests/test_sweep_engine.py -v
git add src/instr_core/api/routes/sweep.py src/instr_core/api/routes/agent.py tests/test_api_server.py tests/test_agent_api.py
git commit -m "refactor: run sweeps through managed sessions"
```

### Task 4: Integrate Dual-Instrument Agents

**Files:**
- Modify: `tests/test_agent_multi_api.py`
- Modify: `src/instr_core/agent/planner.py`
- Modify: `src/instr_core/api/routes/agent.py`

- [ ] **Step 1: Add failing dual-session tests**

Prove both addresses must be connected, resources are not reopened, leases are
acquired in sorted address order, both remain connected after completion, and
an I/O error marks only the failing session unhealthy.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_agent_multi_api.py -v
```

- [ ] **Step 3: Pass borrowed resources into the planner**

Change:

```python
execute_dual_keithley_run(run, source, meter)
```

The planner no longer accepts a ResourceManager or opens resources.

- [ ] **Step 4: Borrow two managed sessions safely**

The route borrows sorted addresses and maps resources back to source/meter
roles. It releases leases in reverse order in `finally`.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_agent_multi_api.py tests/test_session_manager.py -v
git add src/instr_core/agent/planner.py src/instr_core/api/routes/agent.py tests/test_agent_multi_api.py
git commit -m "refactor: use managed dual instrument sessions"
```

### Task 5: Application Shutdown and Desktop State

**Files:**
- Modify: `tests/test_api_server.py`
- Modify: `src/instr_core/api_server.py`
- Modify: `desktop/src/types.ts`
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/components/ConnectedPanel.tsx`
- Modify: `desktop/src/i18n.ts`

- [ ] **Step 1: Add shutdown test**

Use `TestClient` as a context manager and prove lifespan shutdown attempts
teardown for all owned managed resources, closes every session, and closes the
ResourceManager despite individual errors.

- [ ] **Step 2: Implement lifespan cleanup**

Call a dependency helper that performs teardown via managed leases, then calls
`VisaSessionManager.shutdown()`. Continue after every per-session error and log
the summary.

- [ ] **Step 3: Hydrate desktop connections**

On mount, fetch `/visa/connected`; replace local state. `handleConnect` updates
by address rather than appending duplicates.

- [ ] **Step 4: Add desktop disconnect**

Extend `ConnectedPanelProps` with `onDisconnect`. The app calls
`POST /visa/disconnect`, removes only after success, clears selected terminal
address, and displays translated errors.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_api_server.py -v
cd desktop && npm run build
git add src/instr_core/api_server.py tests/test_api_server.py desktop/src/types.ts desktop/src/App.tsx desktop/src/components/ConnectedPanel.tsx desktop/src/i18n.ts
git commit -m "feat: close managed sessions and sync desktop state"
```

### Task 6: Full Verification and Evidence

**Files:**
- Modify: `docs/DESKTOP.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/superpowers/plans/2026-06-20-visa-session-manager.md`

- [ ] **Step 1: Update architecture and desktop documentation**

Document the session manager, real connected state, disconnect/reconnect APIs,
managed-resource requirement, and shutdown cleanup.

- [ ] **Step 2: Audit direct resource opening**

Run:

```bash
rg -n "open_resource" src/instr_core
```

Expected: only `session_manager.py` opens resources.

- [ ] **Step 3: Run full quality gates**

```bash
uv run ruff check src tests
uv run mypy src
uv run pytest tests/ -v
cd desktop && npm run build
cd desktop/src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test
```

- [ ] **Step 4: Record mock-only qualification**

Append exact verification output and state that no real VISA hardware was used.

- [ ] **Step 5: Commit**

```bash
git add docs/DESKTOP.md ARCHITECTURE.md docs/superpowers/plans/2026-06-20-visa-session-manager.md
git commit -m "docs: record managed visa session verification"
```
