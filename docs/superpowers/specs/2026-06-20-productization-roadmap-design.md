# instr-core Productization Roadmap Design

**Date:** 2026-06-20  
**Status:** Approved design  
**Scope:** Safety-complete v0.3, extensible v0.4, and long-term productization

## 1. Objective

Turn `instr-core` from a working instrument-control prototype into a safe,
testable, distributable, and extensible product. Work proceeds continuously
through the highest-priority incomplete item, but every increment must remain
independently runnable and verifiable.

The project continues to enforce its core boundary:

- AI produces typed experiment plans, never executable raw SCPI.
- Every hardware write is validated before a VISA session is touched.
- Unknown or unverifiable hardware state fails closed.
- Real execution requires a valid dry-run and explicit confirmation.
- Every execution path has a best-effort emergency teardown and an audit trail.

## 2. Delivery Model

The roadmap is split into nine stages. Stages are ordered by dependency and
risk, not by UI visibility. Work may move within a stage when tasks are
independent, but a later stage must not weaken an earlier safety invariant.

Each backlog item is complete only when:

1. Behavior and failure semantics are documented.
2. A regression test demonstrates the previous missing behavior.
3. The implementation passes focused and full verification.
4. User-facing documentation is updated when behavior changes.
5. Hardware-sensitive behavior has either real-device evidence or an explicit
   mock-only qualification.

## 3. Safety Invariants

These invariants apply to the REST API, MCP tools, desktop application, agent
workflows, and future protocol adapters.

### 3.1 Validation boundary

- Non-query commands require a loaded and matched schema.
- A missing schema, missing command definition, invalid argument, unknown
  safety state, or failed prerequisite blocks the write.
- Validation occurs before opening or retrieving a VISA resource.
- Query commands are allowed without a schema only when present in a small
  explicit discovery allowlist, initially `*IDN?`.
- `/validate/command` never reports `valid=true` when validation was not
  performed. It returns `valid=false` with actionable issues and suggestions.
- Desktop callers cannot disable validation for hardware writes. Any future
  administrative bypass must be a separately authenticated, audited feature.

### 3.2 Execution boundary

- Dry-run never opens a VISA session.
- Execution requires explicit confirmation tied to the exact validated plan.
- A plan becomes stale when its schema version, connection identity, relevant
  instrument state, or command sequence changes.
- One instrument address can be owned by only one active execution.
- Stop, error, disconnect, timeout, process shutdown, and normal completion all
  invoke the same idempotent teardown path.

### 3.3 Emergency teardown

- The first teardown action is `:OUTP OFF`.
- A failed output-off attempt is logged and retried after 100 ms.
- If retry fails, `*RST` is attempted as a fallback.
- If all attempts fail, a CRITICAL event records the run ID and address.
- Teardown errors never replace the original execution error, but both are
  preserved in the run record.
- A global Emergency Stop endpoint attempts teardown for every active output
  device and returns a per-device result.

### 3.4 Auditability

Every real execution records:

- operator or local session identity;
- confirmation timestamp;
- instrument address and `*IDN?` result;
- schema key, schema version, and content digest;
- typed plan and expanded command sequence;
- validation result and warnings;
- actual commands, responses, timestamps, and errors;
- stop reason and teardown outcome;
- exported data digest.

## 4. Stage 1 — P0 Hardware Safety Closure

### 4.1 Fail-closed command handling

Refactor command handling into a pure preflight step followed by hardware I/O.
Preflight resolves the address-to-schema mapping, parses the command, checks the
query allowlist, validates the command and current state, and returns either an
approved command descriptor or a structured rejection.

Unknown-schema writes return HTTP 422 and do not call `get_visa`,
`ResourceManager.open_resource`, `write`, or `query`.

### 4.2 Unified teardown

Move safe output shutdown into a reusable service shared by single sweep,
multi-instrument workflows, emergency stop, and application shutdown.
The service returns a typed teardown report so callers can persist and display
partial failure instead of relying only on logs.

### 4.3 Limits and execution guards

Apply instrument voltage, current, power, compliance, point-count, command
timeout, and maximum-duration limits at plan validation and immediately before
execution. Configuration defaults remain conservative and cannot exceed schema
limits.

### 4.4 Ownership and emergency stop

Introduce an address ownership registry protected by a lock. Starting a second
run on an owned address returns HTTP 409. Emergency stop and normal teardown
release ownership only after recording the teardown result.

## 5. Stage 2 — Correctness and Runtime Stability

### 5.1 VISA session manager

Replace per-request resource opening with a session manager responsible for:

- connect, disconnect, reconnect, and list-connected operations;
- per-address locks and timeout configuration;
- identity and schema mapping;
- resource cleanup during application shutdown;
- explicit session health and last-error state.

`GET /visa/connected` reports real managed sessions.

### 5.2 Run state model

Use a single explicit lifecycle:

`PLANNED → DRY_RUN → RUNNING → STOPPING → COMPLETED | ABORTED | ERROR`

Invalid transitions are rejected. Run and sweep records are persisted
atomically. Execute requests use an idempotency key so retries cannot start a
second hardware operation.

### 5.3 Error contract and persistence

All API errors use a stable structure containing `code`, `message`,
`suggestions`, `run_id`, and optional details. Stored records use versioned
formats with migration and corruption quarantine. Retention limits bound run,
log, cache, and export storage.

## 6. Stage 3 — Verification and Quality System

### 6.1 Python verification

Add regression, concurrency, fault-injection, API workflow, persistence, and
LLM boundary tests. Coverage gates prioritize `validator`, command preflight,
teardown, session ownership, and execution state transitions.

### 6.2 Frontend and Rust verification

Add Vitest and Testing Library coverage for connection errors, validation
rejections, confirmation, progress, and emergency stop. Add Rust tests for
backend discovery, startup failure, log draining, exit detection, and shutdown.

### 6.3 Continuous integration

GitHub Actions runs:

- Python 3.12 pytest, Ruff, and Mypy;
- TypeScript checking, frontend tests, and Vite production build;
- Rust fmt, Clippy, tests, and check;
- dependency, license, and secret scans;
- macOS, Windows, and Linux packaging smoke builds.

No release artifact is produced from a failing required check.

## 7. Stage 4 — Distributable Desktop Application

Package the Python backend and required dependencies as a Tauri sidecar. The
desktop application must run on a clean supported machine without a separately
installed Python or `uv`.

The Rust shell:

- drains child stdout and stderr continuously;
- waits for `/health` before marking the backend ready;
- reports startup diagnostics in the UI;
- detects crashes and offers a bounded restart;
- detects port conflicts while retaining port 8765 as the protocol contract;
- terminates the backend and invokes shutdown cleanup on exit.

Production enables a restrictive CSP and authenticates local requests with a
per-launch secret. Release workflows cover signing, notarization, installers,
uninstall, upgrade, rollback, and version compatibility.

## 8. Stage 5 — Complete Sweep Product

The sweep subsystem gains:

- live field validation and exact point preview;
- complete UP, DOWN, and BOTH semantics with distinct chart series;
- overflow-to-NaN parsing;
- progress, rate, elapsed time, and remaining-time estimates;
- pause/resume where supported without weakening teardown;
- configurable reset, NPLC, filters, and settling;
- CSV, JSON, and HDF5 exports with experiment metadata;
- persistent searchable history, deletion, and replay;
- incremental SSE or WebSocket updates with reconnect recovery;
- chart downsampling for large datasets;
- repeat sweeps and aggregate statistics;
- an extension interface for CV, pulse, and time-series sweeps.

## 9. Stage 6 — General Agent Platform

Replace workflow-specific plan roots with a versioned `ExperimentPlan` that
contains typed steps and instrument bindings. Existing IV and dual-Keithley
requests remain supported through adapters.

The planning layer:

- receives connected-instrument and capability summaries;
- supports provider abstraction, retry, rate limits, cost records, and offline
  deterministic fallback;
- validates all model output through Pydantic;
- strips unknown fields and rejects raw SCPI;
- supports plan revision, comparison, and revalidation;
- explains how goals map to constraints and commands;
- requires stronger confirmation for classified high-risk plans.

MCP exposes planning, dry-run, execution, stop, status, and export tools with
appropriate annotations. It preserves the same safety boundary as REST.

## 10. Stage 7 — General Multi-Instrument Orchestration

Introduce typed DUT topology, instrument roles, logical ports, and signal
paths. A capability graph verifies that bound instruments can satisfy a plan.

A DAG executor supports:

- dependencies, safe concurrency, barriers, and teardown ordering;
- software synchronization and later hardware triggering;
- trigger ports, edges, polarity, receiver-armed state, and timing constraints;
- common timestamping;
- partial failure and compensating teardown;
- topology validation and wiring guidance;
- reusable sequence templates and a visual sequence editor.

The current dual-Keithley workflow becomes a template on this engine rather
than a separate execution implementation.

## 11. Stage 8 — Protocol and Instrument Ecosystem

Prioritize real-device qualification for Keithley 2600, 2400, and DMM6500,
then extend semantic models to oscilloscopes, power supplies, signal
generators, LCR meters, and DAQ systems.

Protocol support expands across TCPIP, USB, GPIB, serial, binary blocks, and
waveform transfers. Vendor dialect adapters remain below the typed capability
layer.

Automatic identification uses `*IDN?`, USB identifiers, and safe probe
commands. Registry data is versioned and integrity-checked. PDF-derived schema
content is always a reviewable candidate and is never trusted automatically.
Instrument YAML remains in `instr-registry`, not this repository.

## 12. Stage 9 — Product Operations

Long-term product capabilities include:

- workspace and user configuration;
- operator, approver, and read-only roles;
- local authentication and optional enterprise identity;
- tamper-evident audit history;
- retention and export policies;
- redacted diagnostics bundles;
- opt-in reliability and performance telemetry;
- offline operation;
- versioned plugin interfaces and API compatibility;
- database migrations;
- complete localization and accessibility;
- user, safety, support, and release documentation.

Remote hardware execution is excluded until authentication, authorization,
audit, emergency stop, and transport security have all been independently
verified.

## 13. Backlog Tracking

The authoritative implementation backlog lives in the implementation plans
under `docs/superpowers/plans/`. Each task records:

- priority and dependency;
- exact files and interfaces;
- failing test and expected failure;
- implementation steps;
- focused and full verification commands;
- documentation impact;
- real-hardware qualification status.

When a task is completed, its checkboxes and verification evidence are updated
before selecting the next highest-priority incomplete task.

## 14. Initial Implementation Order

The first implementation sequence is:

1. Fail closed for unknown-schema writes and standalone validation.
2. Validate before any VISA resource access.
3. Extract and reuse typed emergency teardown.
4. Apply teardown to dual-instrument execution.
5. Add address ownership and global Emergency Stop.
6. Introduce managed VISA sessions.
7. Establish full run-state and idempotency semantics.
8. Add frontend/Rust tests and continuous integration.
9. Package and verify the Python sidecar.

This order closes immediate physical risk before increasing product surface
area.

## 15. Acceptance

The roadmap itself is complete when all stages have implementation plans with
traceable tasks. The productization objective is complete only when every
planned task is implemented, its required automated checks pass, applicable
real-device qualification is recorded, release artifacts install successfully
on supported platforms, and no unresolved P0 or P1 safety issue remains.
