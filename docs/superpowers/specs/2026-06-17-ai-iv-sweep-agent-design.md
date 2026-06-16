# AI IV Sweep Agent Design

## Goal

Build the first AI experiment-agent workflow for instr-core: a user describes an IV sweep in natural language, instr-core turns it into a structured plan, validates it against the instrument schema, shows a dry-run summary, and only executes against real hardware after explicit confirmation.

## Scope

The first release is intentionally narrow:

- Experiment type: IV sweep only.
- Instrument class: one connected SMU with a matched schema.
- Planner: deterministic rule-based parser, not an LLM integration.
- Execution mode: dry-run by default; real execution requires `confirm=true`.
- Runtime surface: FastAPI Agent API first. MCP and desktop UI can be added on top of the same core module after the API is stable.

This version does not implement arbitrary SCPI planning, multi-instrument orchestration, LLM provider configuration, or a desktop chat interface.

## User Flow

1. User submits a natural-language goal such as:
   `Sweep 0V to 5V in 0.1V steps with 10mA compliance on the connected Keithley.`
2. `POST /agent/plan` parses the goal into a structured `AgentPlan`.
3. `POST /agent/dry-run` validates the plan, expands the safe setup/teardown command preview, and returns issues, warnings, point count, and whether confirmation is required.
4. User reviews the dry-run result.
5. `POST /agent/execute` starts the existing sweep engine only when the plan is valid and `confirm=true`.
6. `GET /agent/runs/{run_id}` returns the plan, dry-run validation, execution status, and linked sweep session id.

## Architecture

Add a new core package:

```text
src/instr_core/agent/
├── __init__.py
├── models.py
├── parser.py
├── planner.py
└── store.py
```

FastAPI gets a thin route layer:

```text
src/instr_core/api/routes/agent.py
```

The agent core owns parsing, plan construction, validation summaries, and in-memory run tracking. The API route owns request/response translation and calls existing registry, address mapping, VISA, and sweep engine dependencies.

## Core Models

`AgentPlan` is the boundary object shared by future LLM, MCP, desktop, and HTTP consumers.

Required fields:

- `plan_id`: stable id for dry-run and execute calls.
- `experiment_type`: currently always `iv_sweep`.
- `mode`: `dry_run` or `execute`.
- `goal`: original natural-language request.
- `instrument_key`: matched registry key.
- `address`: VISA resource address.
- `config`: existing `SweepConfig`.
- `commands`: preview setup, loop placeholder, and teardown commands.
- `requires_confirmation`: always true for real hardware execution.

`AgentRun` stores plan lifecycle state:

- `run_id`
- `plan`
- `validation`
- `status`: `planned`, `dry_run`, `running`, `completed`, `failed`
- `sweep_session_id`
- `error_message`

## Parsing

The MVP parser is deterministic. It extracts:

- start voltage
- stop voltage
- step size
- compliance current
- delay, optional
- direction, optional

Supported units:

- voltage: `V`, `mV`
- current compliance: `A`, `mA`, `uA`, `µA`
- step: same voltage units
- delay: `ms`, `s`

If a required value is missing, planning fails with a clear error listing the missing fields. The parser must not infer dangerous defaults for voltage range or compliance.

## Dry-Run Validation

Dry-run must not touch VISA.

Validation includes:

- instrument key exists
- address has a schema mapping
- plan instrument matches address schema when both are available
- sweep config respects schema global limits
- command preview validates through `validate_command`
- output enable requires compliance state
- point count does not exceed existing sweep limits

Dry-run returns:

- `valid`
- `issues`
- `warnings`
- `suggestions`
- `commands`
- `estimated_points`
- `requires_confirmation`

## Execute

`POST /agent/execute` must reject requests unless:

- `confirm=true`
- the plan exists
- the latest dry-run for that plan is valid
- the address is connected and schema-mapped

Execution delegates to existing `SweepEngine.start_sweep`. It does not duplicate sweep logic.

The agent run stores the returned sweep session id and transitions to `running`. Existing sweep endpoints remain the source of truth for point streaming and CSV export.

## Safety Rules

The agent layer is stricter than a plain sweep request:

- All plans are dry-run first.
- Real execution requires explicit confirmation.
- Missing compliance is fatal.
- Missing instrument/address mapping is fatal.
- Unknown or ambiguous natural-language values are fatal.
- Dry-run is safe to call repeatedly and must never open VISA resources.

## Testing

Add tests for:

- parser handles V, mV, A, mA, uA, delay, and direction
- parser rejects missing start, stop, step, or compliance
- planner creates a valid IV sweep plan for fixture Keithley schema
- dry-run rejects over-limit voltage
- dry-run does not call VISA
- execute rejects missing confirmation
- execute starts sweep through mocked VISA only after valid dry-run
- run lookup returns stored plan and status

## Non-Goals

- No LLM provider integration in the first implementation.
- No arbitrary command-sequence generation.
- No multi-instrument plans.
- No desktop chat UI in this phase.
- No persistent database; run state is in-memory for this release.
