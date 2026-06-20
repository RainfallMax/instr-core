# Unified Run Lifecycle and Idempotent Execution Design

**Date:** 2026-06-20  
**Status:** Approved design  
**Roadmap stage:** Stage 2 — Correctness and Runtime Stability

## 1. Objective

Give every agent execution and sweep a coherent, enforceable lifecycle and make
execution requests safe to retry. A validated plan must execute at most once,
its Agent run must follow the underlying Sweep to a terminal state, and a
backend restart must not preserve a misleading `RUNNING` record.

This increment unifies lifecycle vocabulary and state-transition rules while
retaining the existing single-device and dual-device workflow APIs.

## 2. Scope

Included:

- one shared lifecycle enum for Agent runs and Sweep sessions;
- explicit transition validation;
- execution idempotency keys;
- atomic store operations for transition and idempotency registration;
- validation-context fingerprints;
- single-device Agent/Sweep terminal-state synchronization;
- stop semantics with `STOPPING`;
- persisted timestamps and transition history;
- restart recovery for interrupted runs;
- stable API conflict responses;
- desktop handling of terminal and non-executable states.

Excluded:

- general DAG orchestration;
- resumable hardware execution after process restart;
- database transactions;
- multi-host idempotency;
- durable distributed locks;
- retrying failed physical experiments;
- plan editing UI.

## 3. Unified Lifecycle

### 3.1 States

```text
PLANNED
DRY_RUN
RUNNING
STOPPING
COMPLETED
ABORTED
ERROR
```

Serialized values remain lowercase:

```text
planned, dry_run, running, stopping, completed, aborted, error
```

`FAILED` is migrated to `ERROR`. `SweepStatus.IDLE` is migrated to `PLANNED`.
Legacy persisted JSON accepts old values during loading and is rewritten using
the unified values on the next update.

### 3.2 Allowed transitions

```text
PLANNED  → DRY_RUN
DRY_RUN  → DRY_RUN        # revalidation
DRY_RUN  → RUNNING
RUNNING  → STOPPING
RUNNING  → COMPLETED
RUNNING  → ABORTED
RUNNING  → ERROR
STOPPING → ABORTED
STOPPING → ERROR
```

No terminal state transitions to another state. A new physical execution
requires a new run and a new dry-run.

Planning errors are API request failures and do not create runs. Dry-run
validation failure still transitions to `DRY_RUN`; its validation object is
invalid and execution remains prohibited.

### 3.3 Transition records

Each Agent run and Sweep session stores:

```python
class RunTransition(BaseModel):
    from_status: RunStatus | None
    to_status: RunStatus
    timestamp: str
    reason: str | None = None
```

New runs contain an initial transition from `None` to `PLANNED`.

Run models also contain:

- `created_at`;
- `updated_at`;
- `started_at`;
- `completed_at`;
- `stop_requested_at`;
- `transition_history`.

The transition helper updates timestamps consistently. Callers do not assign
`status` directly.

## 4. State Transition Service

Create a pure shared module:

```python
transition_run(run, target, reason=None, now=None) -> run
can_transition(current, target) -> bool
is_terminal(status) -> bool
```

Invalid transitions raise:

```python
InvalidRunTransition(run_id, current, target)
```

The same helper operates on `AgentRun`, `DualKeithleyRun`, and `SweepSession`
through a small protocol requiring status and timestamp fields.

Transition rules are enforced at:

- plan creation;
- dry-run;
- execution reservation;
- sweep start;
- stop request;
- normal completion;
- abort;
- error;
- persisted-run recovery.

## 5. Execution Idempotency

### 5.1 Request contract

Both endpoints require an HTTP `Idempotency-Key` header:

```http
POST /agent/execute
POST /agent/multi/execute
Idempotency-Key: <opaque client-generated key>
```

Rules:

- key length: 8–128 characters;
- accepted characters: ASCII letters, digits, `.`, `_`, `:`, `/`, `-`;
- missing or invalid key returns HTTP 400;
- the desktop generates one UUID per execution click and retains it until the
  request reaches a definitive response.

The key is scoped to the endpoint plus `run_id`.

### 5.2 Atomic reservation

`AgentRunStore.reserve_execution(run_id, key, context_fingerprint)` executes
under the store lock and returns one of:

```python
ExecutionReservation.NEW
ExecutionReservation.REPLAY
```

For `NEW`, the operation atomically:

1. confirms the run exists;
2. confirms status is `DRY_RUN`;
3. confirms validation is valid;
4. confirms the validation-context fingerprint still matches;
5. records the idempotency key;
6. transitions the run to `RUNNING`;
7. persists the updated record.

For `REPLAY`, the same key and fingerprint returns the current stored run
without starting hardware again. Replays work whether the run is `RUNNING` or
terminal.

A different key for a run that has already reserved execution returns HTTP
409. A key reused with a different fingerprint returns HTTP 409.

Reservation occurs before address ownership and VISA lease acquisition. If
startup fails before the Sweep thread or dual execution begins, the run
transitions to `ERROR`; retrying the same key replays that error instead of
starting a second execution.

### 5.3 Persistence

Each run stores:

```python
execution_idempotency_key: str | None
execution_context_fingerprint: str | None
execution_attempts: int = 0
```

`execution_attempts` becomes `1` on the successful reservation and never
increments for replays.

No global idempotency index is required because keys are scoped by `run_id`.

## 6. Validation Context Fingerprint

### 6.1 Purpose

A dry-run is valid only for the exact plan, schemas, connected identities, and
relevant virtual instrument states it validated.

### 6.2 Canonical payload

The fingerprint is SHA-256 over deterministic JSON containing:

```json
{
  "plan": "<full typed plan model dump>",
  "schemas": {
    "<instrument key>": "<canonical schema model dump>"
  },
  "instruments": {
    "<address>": {
      "idn": "...",
      "schema_key": "...",
      "healthy": true
    }
  },
  "states": {
    "<address>": {
      "output": "OFF"
    }
  }
}
```

JSON is UTF-8, sorted by key, and uses compact separators. The digest is stored
as lowercase hexadecimal.

The canonical schema model dump serves as the current schema version until the
registry contract gains an explicit schema version field.

### 6.3 Dry-run and execute

Dry-run computes and persists:

```python
validation_context_fingerprint: str
validated_at: str
```

Execution recomputes the fingerprint before reservation. Any mismatch returns
HTTP 409:

```text
Validation context changed; run dry-run again before execution
```

A repeated dry-run in `DRY_RUN` replaces the validation and fingerprint and
clears no execution reservation because execution cannot yet have been
reserved.

## 7. Store Atomicity and Persistence

### 7.1 Lock-owned operations

`AgentRunStore` gains:

```python
transition(run_id, target, reason=None) -> Run
reserve_execution(run_id, key, fingerprint) -> ReservationResult
update_from_sweep(run_id, sweep_session) -> Run
recover_interrupted_runs() -> list[str]
```

All read-check-write-persist sequences happen under one `RLock`.

`get()` and `list()` return deep model copies so route handlers cannot mutate
stored runs outside the lock. `create()` rejects duplicate IDs.

### 7.2 Atomic file replacement

Persistence writes JSON to:

```text
<run_id>.json.tmp
```

It flushes and calls `os.fsync`, then replaces the target with `os.replace`.
After replacement it fsyncs the containing directory where supported.

Startup ignores and removes stale `.tmp` files. A malformed primary JSON file
is renamed:

```text
<run_id>.json.corrupt-<timestamp>
```

rather than silently ignored.

### 7.3 Interrupted-run recovery

After loading:

- `RUNNING` and `STOPPING` Agent runs transition to `ERROR`;
- reason and `error_message`:
  `"Backend restarted while execution state was active; hardware state could not be confirmed"`;
- `completed_at` and `updated_at` are set;
- recovery is persisted atomically.

Recovery does not touch hardware because managed VISA sessions do not survive a
process restart. The desktop global emergency-stop remains available after
reconnection, but recovery cannot claim physical teardown succeeded.

## 8. Single-Device Agent/Sweep Synchronization

### 8.1 Start

The Agent execution reservation sets Agent status `RUNNING`. Sweep creation
also starts at `RUNNING` through the transition helper. The Agent stores the
Sweep session ID before the response is returned.

If thread startup fails, both records become `ERROR`.

### 8.2 Completion callback

The Sweep completion callback maps:

```text
Sweep COMPLETED → Agent COMPLETED
Sweep ABORTED   → Agent ABORTED
Sweep ERROR     → Agent ERROR
```

It copies the error message and completion timestamp, persists the Agent run,
updates VISA health when appropriate, then releases address ownership.

The callback catches and logs persistence errors but never skips ownership
release.

### 8.3 Status reads

`GET /agent/runs/{run_id}` returns the persisted synchronized status. It does
not dynamically infer status from Sweep state at read time.

## 9. Stop Semantics

Add:

```http
POST /agent/runs/{run_id}/stop
```

For single-device runs:

1. atomically transition Agent `RUNNING → STOPPING`;
2. transition the linked Sweep `RUNNING → STOPPING`;
3. set the Sweep stop event;
4. return Agent `STOPPING`;
5. completion callback transitions both to `ABORTED` or `ERROR`.

Repeated stop with Agent already `STOPPING` is idempotent and returns the
current run. Stopping a terminal or non-running run returns HTTP 409.

The existing `/sweep/{session_id}/stop` follows identical Sweep transition
rules.

The current synchronous dual-device workflow cannot process an HTTP stop while
its request thread is occupied. This increment exposes no false stop support
for dual runs. The later generalized asynchronous executor will add dual-run
stop. `POST /agent/runs/{run_id}/stop` returns HTTP 409 with an explicit
unsupported message for a running dual-device run.

## 10. API Error Contract

State and idempotency conflicts use HTTP 409 with:

```json
{
  "detail": {
    "code": "RUN_STATE_CONFLICT",
    "message": "...",
    "run_id": "...",
    "current_status": "running"
  }
}
```

Codes in this increment:

- `RUN_STATE_CONFLICT`;
- `IDEMPOTENCY_KEY_REQUIRED`;
- `IDEMPOTENCY_KEY_INVALID`;
- `IDEMPOTENCY_KEY_CONFLICT`;
- `VALIDATION_CONTEXT_STALE`;
- `STOP_NOT_SUPPORTED`.

Invalid confirmation remains HTTP 400. Missing run remains HTTP 404. Hardware
startup/runtime errors remain HTTP 500 while the persisted run becomes
`ERROR`.

## 11. Desktop Behavior

Execution:

- generate a UUID idempotency key for each run execution action;
- reuse the key while the same request is pending or retried after network
  ambiguity;
- clear it only when a new plan/dry-run is created;
- disable Execute unless status is `DRY_RUN` and validation is valid;
- disable plan and dry-run controls while status is `RUNNING` or `STOPPING`.

Single-device Agent UI gains Stop when status is `RUNNING` or `STOPPING`.
Current desktop does not expose the single-device Agent panel directly, so
backend support is implemented and shared types are updated; the control is
used when that panel is introduced.

Dual-device UI:

- sends `Idempotency-Key`;
- shows `ERROR` instead of legacy `FAILED`;
- disables repeat execution after reservation;
- does not show a Stop button for the synchronous dual workflow.

## 12. Migration

Pydantic pre-validation maps:

```text
failed → error
idle   → planned
```

Legacy records without transition history receive a synthetic history entry
for their loaded status at load time.

Existing desktop and API clients must add `Idempotency-Key` to execute calls.
This intentional contract break is documented because retry-safe physical
execution is more important than permissive compatibility.

## 13. Testing

### 13.1 Transition tests

- every allowed edge succeeds;
- every unlisted edge fails;
- timestamps and history are correct;
- terminal states are immutable;
- legacy enum values migrate.

### 13.2 Store tests

- get/list return copies;
- duplicate create fails;
- transition is atomic under concurrency;
- one of ten concurrent reservations wins;
- same-key replay returns the same run;
- different-key replay conflicts;
- stale fingerprint conflicts;
- JSON replacement leaves no partial target;
- corrupt file is quarantined;
- restart recovers active runs to `ERROR`.

### 13.3 API tests

- missing/invalid idempotency key;
- same-key execute replay does not touch VISA twice;
- different key returns 409;
- stale context returns 409 before ownership or VISA;
- single Agent follows Sweep completion/error/abort;
- stop enters `STOPPING` then `ABORTED`;
- terminal execution cannot restart;
- dual run uses reservation semantics.

### 13.4 Desktop checks

Before Stage 3 introduces Vitest:

- TypeScript build confirms status union and headers;
- source inspection confirms key reuse;
- existing backend API tests prove physical at-most-once behavior.

## 14. Acceptance Criteria

This increment is complete when:

1. Agent and Sweep models use the unified lifecycle values.
2. No route or engine assigns a run status outside the transition service.
3. Execute endpoints require and atomically reserve valid idempotency keys.
4. Same-key retries never start hardware twice.
5. Different-key or terminal re-execution returns a deterministic conflict.
6. Execution rejects stale dry-run context before hardware access.
7. Single-device Agent status reaches the same terminal outcome as its Sweep.
8. Stop uses `STOPPING` and completes as `ABORTED` or `ERROR`.
9. Persisted active runs recover to `ERROR` after restart.
10. Run files use atomic replacement and corrupt records are quarantined.
11. Python, frontend, and Rust quality gates pass.
12. Hardware qualification remains explicitly mock-only until real-device
    testing is recorded.
