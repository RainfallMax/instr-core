# Unified Run Lifecycle and Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce one shared run lifecycle, atomic idempotent execution, stale dry-run rejection, synchronized Agent/Sweep terminal states, safe stop semantics, and restart recovery.

**Architecture:** A pure lifecycle module owns transitions and fingerprints. `AgentRunStore` owns all atomic read-check-write-persist operations and idempotency reservations. API routes compute current validation context, reserve execution before hardware access, and synchronize asynchronous Sweep outcomes through store callbacks.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SHA-256 canonical JSON, React/TypeScript, pytest, Ruff, Mypy

---

### Task 1: Shared Lifecycle Models and Transition Service

**Files:**
- Create: `src/instr_core/run_lifecycle.py`
- Create: `tests/test_run_lifecycle.py`
- Modify: `src/instr_core/agent/models.py`
- Modify: `src/instr_core/sweep/models.py`
- Modify: `src/instr_core/sweep/engine.py`

- [ ] Write tests for every allowed/forbidden transition, terminal immutability,
  timestamp/history updates, and legacy `failed`/`idle` migration.
- [ ] Run `uv run pytest tests/test_run_lifecycle.py -v` and verify RED.
- [ ] Add `RunStatus`, `RunTransition`, `InvalidRunTransition`,
  `transition_run`, `can_transition`, and `is_terminal`.
- [ ] Replace Agent/Sweep status enums with aliases to `RunStatus`; add
  lifecycle timestamps and histories to run/session models.
- [ ] Refactor SweepEngine start, stop, completion, abort, and error to use
  `transition_run`.
- [ ] Run lifecycle and Sweep tests, Ruff, and Mypy.
- [ ] Commit: `feat: unify experiment run lifecycle`.

### Task 2: Atomic Agent Store and Recovery

**Files:**
- Modify: `src/instr_core/agent/store.py`
- Modify: `tests/test_agent_store.py`

- [ ] Write tests proving duplicate create rejection, copy-returning reads,
  atomic transition under concurrency, atomic temp-file replacement, corrupt
  quarantine, stale temp cleanup, and active-run restart recovery.
- [ ] Verify RED.
- [ ] Implement deep-copy `get/list`, duplicate-safe `create`, lock-owned
  `transition`, atomic `os.replace` persistence, quarantine, and
  `recover_interrupted_runs`.
- [ ] Run store tests and quality checks.
- [ ] Commit: `feat: make agent run storage atomic`.

### Task 3: Validation Context Fingerprints

**Files:**
- Create: `src/instr_core/agent/context.py`
- Create: `tests/test_agent_context.py`
- Modify: `src/instr_core/agent/models.py`
- Modify: `src/instr_core/api/dependencies.py`
- Modify: `src/instr_core/api/routes/agent.py`

- [ ] Test deterministic fingerprints, changes for plan/schema/IDN/state, and
  ordering independence.
- [ ] Verify RED.
- [ ] Implement canonical JSON fingerprint computation for single and dual
  runs using Registry, managed session metadata, and address-state snapshots.
- [ ] Persist fingerprint and validated timestamp during dry-run.
- [ ] Add helpers returning full address-state snapshots.
- [ ] Run focused tests and commit:
  `feat: bind dry runs to validation context`.

### Task 4: Atomic Idempotency Reservations

**Files:**
- Modify: `src/instr_core/agent/store.py`
- Modify: `src/instr_core/agent/models.py`
- Modify: `src/instr_core/api/routes/agent.py`
- Modify: `tests/test_agent_store.py`
- Modify: `tests/test_agent_api.py`
- Modify: `tests/test_agent_multi_api.py`

- [ ] Test key validation, one winner among concurrent keys, same-key replay,
  different-key conflict, fingerprint conflict, terminal replay, and attempt
  count.
- [ ] Verify RED.
- [ ] Add `ExecutionReservation`, reservation result/errors, persisted
  execution key/fingerprint/attempts, and `reserve_execution`.
- [ ] Require `Idempotency-Key` headers on execute endpoints and return stable
  HTTP 400/409 detail objects.
- [ ] Recompute fingerprints before reservation; reject stale contexts before
  ownership or VISA.
- [ ] Make same-key replay return the current stored run without hardware.
- [ ] Run focused API/store tests and commit:
  `feat: make agent execution idempotent`.

### Task 5: Sweep Synchronization and Stop

**Files:**
- Modify: `src/instr_core/agent/store.py`
- Modify: `src/instr_core/api/routes/agent.py`
- Modify: `src/instr_core/api/routes/sweep.py`
- Modify: `src/instr_core/sweep/engine.py`
- Modify: `tests/test_agent_api.py`
- Modify: `tests/test_api_server.py`

- [ ] Test Agent completion/error/abort synchronization, `RUNNING → STOPPING`,
  repeated stop, terminal stop conflicts, and dual stop unsupported.
- [ ] Verify RED.
- [ ] Add `update_from_sweep`; make callbacks persist Agent terminal outcomes
  before releasing ownership.
- [ ] Add `POST /agent/runs/{run_id}/stop`; update Sweep stop endpoint and
  engine transitions.
- [ ] Ensure startup errors transition reserved runs to `ERROR`.
- [ ] Run focused tests and commit:
  `feat: synchronize and stop agent runs`.

### Task 6: Desktop Contract, Migration, and Full Verification

**Files:**
- Modify: `desktop/src/types.ts`
- Modify: `desktop/src/components/agent/DualKeithleyPanel.tsx`
- Modify: `desktop/src/i18n.ts`
- Modify: `README.md`
- Modify: `README_zh-CN.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/superpowers/plans/2026-06-20-run-lifecycle-idempotency.md`

- [ ] Add the unified status union and UUID idempotency-key reuse to the dual
  UI; disable invalid execution and show `error`.
- [ ] Document lifecycle, required header, stale dry-run, stop, and restart
  recovery.
- [ ] Audit direct status assignment:
  `rg -n "\\.status\\s*=" src/instr_core`.
- [ ] Run:
  `uv run ruff check src tests`,
  `uv run mypy src`,
  `uv run pytest tests/ -v`,
  `npm run build`,
  and Rust fmt/clippy/test.
- [ ] Record exact evidence and mock-only qualification.
- [ ] Commit: `docs: record idempotent lifecycle verification`.
