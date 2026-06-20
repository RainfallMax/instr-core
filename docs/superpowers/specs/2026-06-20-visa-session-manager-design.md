# VISA Session Manager Design

**Date:** 2026-06-20  
**Status:** Approved design  
**Roadmap stage:** Stage 2 — Correctness and Runtime Stability

## 1. Objective

Replace ad hoc `ResourceManager.open_resource()` calls with an application-wide
VISA session manager. A successful `/visa/connect` creates one managed session
that is reused by manual commands, sweeps, agent workflows, and emergency
teardown until the user disconnects or the application shuts down.

The manager must make connection state observable, serialize access to each
resource, prevent half-created sessions, and close resources deterministically.

## 2. Scope

This increment includes:

- managed connect, get, disconnect, reconnect, list, and shutdown operations;
- one reusable VISA resource per connected address;
- per-address locking;
- real `GET /visa/connected` results;
- `POST /visa/disconnect` and `POST /visa/reconnect`;
- reuse by command, sweep, agent, and emergency-stop paths;
- startup/lifespan initialization and shutdown cleanup;
- desktop restoration of connected sessions and manual disconnect;
- deterministic mock-VISA tests.

This increment does not include:

- persistence of live connections across backend process restarts;
- automatic background reconnect loops;
- remote VISA gateways;
- database-backed session metadata;
- arbitrary user-configurable timeout policy;
- the later unified experiment run-state model.

## 3. Core Model

### 3.1 Managed session

Each address maps to one `ManagedVisaSession`:

```python
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

The resource is internal and never serialized. API responses use
`ConnectedInstrument`, extended with:

- `connected_at`;
- `healthy`;
- `last_error`.

The identity fields and schema key are captured when the connection is created.
They are not re-queried on every list operation.

### 3.2 Manager

`VisaSessionManager` owns:

- the lazy ResourceManager supplier;
- a registry lock protecting the session dictionary;
- all managed resources;
- connect/disconnect/reconnect/shutdown behavior.

Public methods:

```python
connect(address, identify) -> ManagedVisaSession
get(address) -> ManagedVisaSession
get_resource(address) -> context manager yielding resource under address lock
list_connected() -> list[ConnectedInstrument]
disconnect(address, *, force=False) -> ConnectedInstrument
reconnect(address, identify) -> ManagedVisaSession
shutdown(teardown) -> ShutdownReport
```

`identify` is a callback owned by the API layer that performs `*IDN?`, parses
identity, and resolves a schema. This keeps Registry concerns out of the
generic resource manager while preserving one atomic connect operation.

## 4. Connection Semantics

### 4.1 Connect

Connect follows this sequence:

1. Normalize and reject an empty address.
2. Under the manager registry lock, return the existing healthy session if one
   already exists. Repeated connect is idempotent.
3. Open a temporary resource outside the registry lock.
4. Under the resource's future per-address lock, issue `*IDN?`.
5. Resolve `ConnectedInstrument` and schema metadata.
6. Under the registry lock, publish the fully initialized session.
7. If another thread published the same address first, close the duplicate
   temporary resource and return the existing session.

If open, identification, parsing, or schema resolution raises:

- close the temporary resource if it exists;
- publish no session;
- preserve no address state mapping;
- return an API error.

An unrecognized instrument may still connect with `schema_key=None`, but P0
fail-closed rules continue to reject non-allowlisted hardware commands.

### 4.2 Get and resource access

All hardware consumers call `get_resource(address)`. It:

- raises a typed `SessionNotFound` error when disconnected;
- acquires the session's `RLock`;
- checks `healthy`;
- yields the existing resource;
- records the exception text and sets `healthy=False` when I/O fails;
- releases the lock in all cases.

The manager does not automatically reopen an unhealthy session. The caller or
user must invoke reconnect, making state changes explicit and auditable.

### 4.3 Disconnect

Normal disconnect:

1. Check address ownership before entering the manager.
2. Return HTTP 409 if an active sweep/agent owns the address.
3. Remove the session from the manager registry, preventing new borrowers.
4. Acquire the session lock and call `resource.close()`.
5. Remove address schema and virtual state mappings.
6. Return the disconnected instrument metadata.

Closing failure returns HTTP 500 but the session remains removed: a resource
that failed to close cannot be represented as a healthy reusable connection.
The error is logged at ERROR level.

Disconnecting an unknown address returns HTTP 404.

### 4.4 Reconnect

Reconnect is an explicit replace operation:

1. Reject HTTP 409 if the address is owned by an active operation.
2. Remove and close any existing session.
3. Clear schema and virtual state mappings.
4. Perform a fresh connect and `*IDN?`.

If close fails, reconnect stops and reports the close error. If the new connect
fails, the address remains disconnected rather than restoring a stale session.

## 5. Consumer Integration

### 5.1 Manual commands

`/visa/command` retains P0 ordering:

1. command preflight;
2. session lookup;
3. per-address lock;
4. hardware I/O;
5. virtual state update.

No fallback opens an unmanaged resource. Sending a command to a mapped but
disconnected address returns HTTP 409 with guidance to connect.

### 5.2 Sweeps

`/sweep/start` validates schema and acquires address ownership before borrowing
the managed resource. The sweep thread receives a manager lease rather than a
bare resource that can be disconnected concurrently.

The lease holds the per-address lock for the full sweep. Completion releases
the lease and then ownership. The session remains connected after a completed,
aborted, or recoverable failed sweep. A VISA I/O failure marks it unhealthy.

### 5.3 Agent workflows

Single-device execution uses the same sweep lease.

Dual-device execution borrows sessions in sorted-address order to avoid lock
inversion. It releases them in reverse order. Address ownership is acquired
before session borrowing. Missing or unhealthy sessions fail before any command
is sent to either instrument.

### 5.4 Emergency stop

Emergency stop operates on active ownership addresses and retrieves the
corresponding managed session. It never creates a new unmanaged connection.

If an owned address has no managed session, its result is unsafe with an
explicit error. Safe teardown releases ownership; unsafe teardown keeps
ownership, matching P0 behavior.

## 6. API Contract

### 6.1 Connect

```http
POST /visa/connect?address=USB0::...
```

Returns `ConnectedInstrument`. Repeated calls return the existing session and
do not issue another `*IDN?`.

### 6.2 Connected list

```http
GET /visa/connected
```

Returns connected sessions ordered by `connected_at`, then address. It returns
an empty list only when no sessions exist.

### 6.3 Disconnect

```http
POST /visa/disconnect?address=USB0::...
```

Responses:

- 200: disconnected metadata;
- 404: no managed session;
- 409: address is owned by an active operation;
- 500: resource close failure.

### 6.4 Reconnect

```http
POST /visa/reconnect?address=USB0::...
```

Responses follow connect plus HTTP 409 for active ownership.

### 6.5 Command session errors

Disconnected or unhealthy sessions return HTTP 409 rather than opening a new
resource. Validation failures remain HTTP 422. Hardware I/O failures remain
HTTP 500 and update session health.

## 7. Application Lifecycle

`init_app_state` creates one `VisaSessionManager`.

FastAPI lifespan shutdown:

1. snapshot active address ownership;
2. attempt shared safe teardown for each owned managed resource;
3. close every managed resource;
4. close the ResourceManager if it exposes `close()`;
5. log a summary containing safe/unsafe teardown and close failures.

Shutdown continues after individual errors and never leaves later sessions
unattempted. The shutdown report is testable even though it is not initially
exposed as an endpoint.

## 8. Desktop Behavior

On application mount, the desktop fetches `/visa/connected` and replaces its
local connection list. This makes frontend refreshes consistent with backend
state.

Connected instruments gain a Disconnect action:

- disabled while the request is pending;
- removes the instrument only after a successful backend response;
- clears terminal selection if the disconnected address was selected;
- displays backend conflict/error messages;
- does not offer a force-disconnect action.

Repeated connect responses update the existing address entry rather than
creating duplicate rows.

Reconnect UI is deferred. Users can disconnect and connect again; the endpoint
is implemented for API clients and later UI use.

## 9. Concurrency and Lock Ordering

Global order:

1. address ownership registry;
2. session manager registry lock;
3. per-address session locks sorted lexicographically.

No hardware I/O occurs while holding the session manager registry lock.
Callbacks that access Registry or address-state helpers execute outside the
manager registry lock.

Disconnect removes a session from discoverability before waiting for its
session lock. Existing borrowers complete; new borrowers fail. Active
operations are already protected by ownership, so ordinary disconnect will not
enter this wait in supported API flows.

## 10. Error Handling

Typed internal errors:

- `SessionNotFound`;
- `SessionUnhealthy`;
- `SessionConnectError`;
- `SessionCloseError`.

All exceptions preserve the address and original cause. API routes translate
them into the status codes defined above. Logs never include VISA credentials
if future address formats contain secrets; address redaction is a later
cross-cutting diagnostics task.

## 11. Testing

### 11.1 Manager unit tests

- successful connect and identity capture;
- idempotent duplicate connect;
- concurrent duplicate connect closes the loser;
- failed identification closes temporary resource and publishes nothing;
- resource lease serializes concurrent calls;
- I/O failure marks a session unhealthy;
- disconnect closes once and removes the session;
- reconnect replaces the resource;
- shutdown attempts every session and closes ResourceManager.

### 11.2 API tests

- `/visa/connected` returns actual sessions;
- commands reuse the connected resource without another open;
- disconnected and unhealthy commands return 409;
- disconnect rejects active ownership;
- reconnect rejects active ownership;
- schema/state mappings are cleared on disconnect;
- emergency stop uses managed resources only;
- sweeps and agent workflows require connected sessions.

### 11.3 Desktop checks

Until Vitest is introduced in Stage 3:

- TypeScript and Vite production build;
- manual source-level verification of initial connected-session hydration;
- manual source-level verification of disconnect state updates.

## 12. Compatibility and Migration

The public connect response remains compatible except for additive health
fields. Existing clients that ignore new fields continue to work.

Behavior intentionally changes:

- `/visa/connected` now returns real sessions;
- hardware commands and executions require a managed connection;
- repeated connect no longer opens duplicate resources;
- direct route-level `open_resource` calls are removed.

The `api_server.pyvisa` test compatibility hook remains until tests migrate to
dependency injection in a later cleanup.

## 13. Acceptance Criteria

This increment is complete when:

1. No API route or agent planner directly calls `ResourceManager.open_resource`.
2. Every connected address has exactly one managed resource.
3. Commands and experiments reuse managed resources under per-address locks.
4. Connected, disconnect, reconnect, health, and shutdown semantics match this
   specification.
5. Active ownership prevents normal disconnect and reconnect.
6. Emergency stop and application shutdown attempt all relevant sessions.
7. Failed connections publish no session or address-state mapping.
8. Python, frontend, and Rust quality gates pass.
9. Qualification is explicitly recorded as mock-only until real instruments
   are tested.
