# instr-core Architecture

This document describes the technical architecture of `instr-core`, including both the MCP server workflow and the Tauri desktop application.

> **Purpose**: Help future AI assistants and contributors understand how the project is structured, how components communicate, and where to make changes.

---

## Table of Contents

1. [High-Level Overview](#high-level-overview)
2. [Shared Python Core](#shared-python-core)
3. [MCP Server Workflow](#mcp-server-workflow)
4. [Desktop App Workflow](#desktop-app-workflow)
5. [Communication Protocols](#communication-protocols)
6. [Data Flow](#data-flow)
7. [File Layout](#file-layout)
8. [Technology Decisions](#technology-decisions)

---

## High-Level Overview

`instr-core` is a **hybrid Python + Rust + TypeScript** project with two user-facing interfaces that share the same validation engine:

| Interface | User | Transport | Entry Point |
|-----------|------|-----------|-------------|
| MCP Server | AI assistants (Claude, Cursor, etc.) | stdio JSON-RPC | `main.py` |
| Desktop App | Human engineers | HTTP + native window | `desktop/src-tauri/src/main.rs` |

Both interfaces use the same Python code for:
- Loading and caching instrument YAML schemas
- Validating SCPI commands against safety rules
- Tracking virtual instrument state across command sequences

The desktop app adds:
- Direct PyVISA instrument communication
- A React-based UI for manual instrument control
- A native desktop window via Tauri

### Managed VISA sessions

The FastAPI runtime owns one `VisaSessionManager`. `POST /visa/connect`
creates and identifies one reusable resource per address. Commands, sweeps,
agent workflows, and emergency stop borrow that resource under a per-address
lock; API routes do not open unmanaged resources.

`GET /visa/connected` reports live in-memory sessions.
`POST /visa/disconnect` closes an idle session, while
`POST /visa/reconnect` explicitly replaces it. Active experiment ownership
blocks ordinary disconnect and reconnect. FastAPI shutdown attempts safe
teardown for owned outputs before closing all sessions and the ResourceManager.

### Run lifecycle and execution reservation

Agent runs and Sweep sessions share `RunStatus` and the transition service in
`run_lifecycle.py`. The persisted lifecycle is
`planned → dry_run → running → stopping → completed/aborted/error`; terminal
states are immutable.

Dry-run persists a SHA-256 fingerprint of the plan, schemas, connected
instrument identities, session health, and tracked address state. Execute
recomputes that context before hardware access and rejects stale validation.
`AgentRunStore.reserve_execution` atomically records the required
`Idempotency-Key`, fingerprint, and attempt count before address ownership or
VISA access. Same-key retries replay the stored run without executing hardware.

Single-device Agent callbacks persist the linked Sweep terminal state before
releasing address ownership. The stop endpoint transitions
`running → stopping`; the Sweep worker then records `aborted`. Synchronous
dual-device runs do not advertise partial stop support. Store startup
quarantines corrupt records and converts interrupted `running`/`stopping` runs
to `error`.

---

## Shared Python Core

The shared core lives in `src/instr_core/` and is used by both workflows.

### Module Map

```
src/instr_core/
├── __init__.py
├── schema.py            # Pydantic models for YAML schema
├── validator.py         # Validation engine (the "firewall")
├── registry_client.py   # Remote YAML fetching + caching
├── server.py            # FastMCP tools, prompts, resources
├── main.py              # MCP CLI entry point
└── api_server.py        # FastAPI HTTP service (desktop only)
```

### schema.py

Pydantic models that define the YAML schema structure:

- `InstrumentSchema` — top-level schema object
- `InstrumentInfo` — manufacturer, model, description
- `GlobalLimits` — voltage/current/power/frequency maxima
- `CommandDef` — individual SCPI command with constraints
- `ParameterDef` — command parameters and allowed values
- `Range` — numeric min/max
- `SequenceRule` — before/after state requirements
- `Safety` — compliance requirements and sequencing rules

**Key principle**: All schema validation happens through these models. If a YAML file doesn't match the Pydantic schema, it fails at load time.

### validator.py

The validation engine. Stateless functions that take a schema and a proposed command, return a `ValidationResult`.

Key functions:
- `validate_command(schema, command, argument, current_state)` — validates a single command
- `check_requires()` — verifies prerequisite state conditions
- `check_forbidden_when()` — checks prohibited state combinations
- `check_argument()` — validates parameter values against allowed values
- `check_global_limits()` — ensures values don't exceed instrument-wide limits
- `check_sequence_rules()` — enforces before/after ordering constraints

**Key principle**: The engine is conservative — when in doubt, reject the command. This is the "firewall" that prevents dangerous code from reaching hardware.

### Registry

The `Registry` class in `validator.py` manages instrument schemas:

- Scans directories for `.yaml` / `.yml` files
- Lazy-loads and caches schemas
- Thread-safe (uses `threading.RLock`)
- Supports local directories and remote `RegistryClient`

Schema lookup key format: `vendor/type/model` (e.g., `keithley/smu/2600`)

---

## MCP Server Workflow

The MCP (Model Context Protocol) server allows AI assistants to query instrument capabilities and validate commands before generating code.

### Entry Point

```bash
uv run instr-core
# or
python -m instr_core.main
```

### Transport

Uses `stdio` transport — the MCP server reads JSON-RPC messages from stdin and writes responses to stdout. This is how Claude Desktop, Cursor, and Claude Code communicate with the server.

### Tools

| Tool | Purpose |
|------|---------|
| `server_status` | Health check |
| `list_instruments` | Browse available instruments |
| `search_instruments` | Filter by manufacturer, category, keyword |
| `get_command_tree` | Get all SCPI commands for an instrument |
| `get_command_detail` | Get constraints for a specific command |
| `get_safety_limits` | Get global safety boundaries |
| `validate_instrument_state` | Validate a single command |
| `validate_command_sequence` | Validate a multi-step sequence |

### Prompts

| Prompt | Purpose |
|--------|---------|
| `get_instrument_sop` | Inject full schema context into AI for code generation |
| `smu_safe_voltage_setup` | Step-by-step voltage setup guide |
| `smu_safe_current_setup` | Step-by-step current setup guide |
| `scpi_safety_guide` | General usage guidelines |
| `instrument_init` | Safe initialization sequence |
| `scope_measure_setup` | Measurement setup for scopes/DMMs |

### Resources

Instruments are exposed as MCP resources with URIs like `instr://keithley/smu/2600`. AI assistants can read the full YAML schema by accessing these URIs.

---

## Desktop App Workflow

The desktop app provides a native GUI for instrument control. It is built as a **Tauri** application with a React frontend and a Python backend.

### Architecture Diagram

```
┌─────────────────────────────────────────────┐
│  Tauri Desktop Window                       │
│  ┌─────────────────────────────────────┐   │
│  │  React UI (WebView)                 │   │
│  │  - Instrument browser               │   │
│  │  - VISA resource scanner            │   │
│  │  - SCPI terminal                    │   │
│  │  - Data visualization (future)      │   │
│  └─────────────────────────────────────┘   │
│              ↕ HTTP fetch                  │
│  ┌─────────────────────────────────────┐   │
│  │  Rust Shell (Tauri)                 │   │
│  │  - Spawns Python child process      │   │
│  │  - Manages window lifecycle         │   │
│  │  - Native menus / dialogs           │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Python Backend Process                     │
│  ┌─────────────────────────────────────┐   │
│  │  FastAPI (port 8765)                │   │
│  │  - /instruments                     │   │
│  │  - /visa/resources                  │   │
│  │  - /visa/command                    │   │
│  │  - /validate/command                │   │
│  └─────────────────────────────────────┘   │
│              ↕ shared memory               │
│  ┌─────────────────────────────────────┐   │
│  │  Shared Core                        │   │
│  │  - Registry                         │   │
│  │  - Validator                        │   │
│  │  - PyVISA ResourceManager           │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Rust Shell (`desktop/src-tauri/src/main.rs`)

Responsibilities:
1. **Find Python backend** — looks for `api_server.py` in development or bundled resources in production
2. **Spawn child process** — runs `uv run python api_server.py` or `python api_server.py`
3. **Set environment** — `INSTR_CORE_API_PORT=8765`
4. **Lifecycle management** — kills Python process when window closes

### React Frontend (`desktop/src/App.tsx`)

A single-page application with four main panels:

1. **Instrument Schemas** — browse loaded schemas from the registry
2. **VISA Resources** — scan and connect to physical instruments
3. **Connected Instruments** — manage active connections
4. **SCPI Terminal** — send commands and view responses with validation feedback

Styling uses a custom dark theme (`App.css`) inspired by Catppuccin colors.

### FastAPI Backend (`src/instr_core/api_server.py`)

Exposes REST endpoints for the React UI:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Server status |
| `/instruments` | GET | List all schemas |
| `/instruments/{key}` | GET | Get full schema |
| `/instruments/{key}/safety-limits` | GET | Get safety boundaries |
| `/instruments/{key}/commands` | GET | Get command tree |
| `/validate/command` | POST | Validate a command |
| `/visa/resources` | GET | Scan VISA resources |
| `/visa/connect` | POST | Connect to instrument |
| `/visa/command` | POST | Send SCPI command |
| `/visa/connected` | GET | List active connections |
| `/visa/disconnect` | POST | Close an idle managed session |
| `/visa/reconnect` | POST | Replace an idle managed session |
| `/visa/emergency-stop` | POST | Teardown all actively owned addresses |
| `/agent/execute` | POST | Idempotently execute a validated single-device run |
| `/agent/runs/{run_id}/stop` | POST | Stop a running single-device Agent run |
| `/agent/multi/execute` | POST | Idempotently execute a validated dual-device run |

---

## Communication Protocols

### MCP: stdio JSON-RPC

The MCP server uses `mcp.server.fastmcp.FastMCP` which handles stdio transport automatically. Each message is a JSON-RPC 2.0 request/response.

### Desktop: HTTP REST

The React UI communicates with Python via standard HTTP:

```typescript
const API_BASE = "http://localhost:8765";

// Example: send a SCPI command
const res = await fetch(`${API_BASE}/visa/command`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    address: "USB0::0x05E6::0x2600::INSTR",
    command: ":SOUR:VOLT 10",
    validate: true,
  }),
});
const data = await res.json();
```

CORS is configured in `api_server.py` to allow:
- `http://localhost:1420` (Vite dev server)
- `tauri://localhost` (Tauri production webview)

---

## Data Flow

### MCP Workflow

```
1. AI calls tool (e.g., validate_instrument_state)
2. server.py receives the call
3. validator.py loads schema from Registry
4. validator.py checks command against rules
5. server.py formats result as text
6. AI receives text response
```

### Desktop Workflow

```
1. User clicks "Send" in SCPI terminal
2. React sends POST to /visa/command
3. api_server.py receives the request
4. (Optional) validator.py validates the command
5. api_server.py calls PyVISA to send the command
6. api_server.py returns JSON response
7. React displays response in terminal
```

### Schema Loading

```
1. Registry scans directories for *.yaml
2. On first access, Registry loads and parses YAML
3. Pydantic validates the YAML structure
4. Schema is cached in memory
5. Subsequent accesses use cached instance
```

---

## File Layout

```
instr-core/
├── src/instr_core/              # Shared Python core
│   ├── __init__.py
│   ├── schema.py               # Pydantic models
│   ├── validator.py            # Validation engine
│   ├── registry_client.py      # Remote YAML client
│   ├── server.py               # FastMCP server
│   ├── main.py                 # MCP CLI entry
│   └── api_server.py           # FastAPI HTTP server
│
├── desktop/                     # Tauri desktop app
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx            # React entry
│       ├── App.tsx             # Main UI
│       └── App.css             # Dark theme
│   └── src-tauri/
│       ├── Cargo.toml          # Rust deps
│       ├── tauri.conf.json     # Window config
│       ├── build.rs            # Build script
│       └── src/
│           ├── main.rs         # Rust entry (spawns Python)
│           └── lib.rs          # Library entry
│
├── tests/                       # Python tests
│   ├── test_schema.py
│   ├── test_validator.py
│   └── test_registry_client.py
│
├── tests/fixtures/registry/     # Local test schemas
│   └── keithley/
│       └── smu/
│           └── 2600.yaml
│
├── pyproject.toml               # Python deps + build config
├── .ruff.toml                   # Python linting config
├── README.md                    # English docs
├── README_zh-CN.md             # Chinese docs
├── AGENTS.md                    # AI behavior constraints
├── CONTRIBUTING.md              # Contributor guide
└── ARCHITECTURE.md             # This file
```

---

## Technology Decisions

### Why Python for the core?

- **PyVISA ecosystem**: Scientific instrument control is dominated by Python. Rewriting in Rust would require re-implementing VISA drivers.
- **MCP SDK maturity**: The official MCP Python SDK (FastMCP) is the most mature and documented.
- **Schema flexibility**: YAML parsing and dynamic validation are more ergonomic in Python.

### Why Tauri for the desktop?

- **Lightweight**: ~5MB vs Electron's ~100MB+
- **Native window**: Rust handles window management, menus, system integration
- **Web frontend**: React provides modern UI development with rich ecosystem
- **Security**: Tauri's security model is stricter than Electron's

### Why FastAPI for the HTTP layer?

- **Type safety**: Pydantic models shared with the MCP server
- **Async**: Handles concurrent requests from UI
- **Auto-docs**: `/docs` endpoint generates OpenAPI documentation
- **Lightweight**: Minimal overhead compared to Django/Flask

### Why not a single-process architecture?

The Python backend runs as a **child process** of the Tauri app rather than being embedded:

- **Independent debugging**: Can run `api_server.py` standalone without Tauri
- **Language boundaries**: Python and Rust have different GC/memory models; separate processes avoid GIL issues
- **Graceful degradation**: If the UI crashes, the Python backend can continue running (and vice versa)
- **Future extensibility**: Could run Python on a remote machine while UI is local

### Communication: HTTP vs IPC

We chose **HTTP** over Tauri's IPC mechanism for Python-Rust communication:

- **Simplicity**: Standard fetch API on frontend, standard FastAPI on backend
- **Future-proofing**: Could eventually run backend on a different machine
- **Debugging**: Can use curl/browser to test endpoints independently
- **Trade-off**: Slightly higher latency than IPC, but negligible for instrument control (ms vs μs)
