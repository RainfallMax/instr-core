# Dual Keithley Software-Synchronized Sweep

## Purpose

This is the first multi-instrument agent workflow for instr-core. It uses a
Keithley 2600 SMU as the source instrument and a Keithley DMM6500 as the meter
instrument. The workflow is deliberately software-synchronized first: the SMU
sets each bias point, the agent waits for settling, the DMM reads one value, and
the run records `(source_voltage, meter_value, timestamp)`.

This is the recommended stepping stone before hardware trigger coordination.

## MVP Scope

- Source instrument: `keithley/smu/2600`
- Meter instrument: `keithley/dmm/dmm6500`
- Experiment type: `dual_keithley_sweep`
- Synchronization: software loop, not hardware trigger
- Planning: explicit structured request fields, no LLM parsing yet
- Safety: dry-run first, confirmed execution only
- Output: in-memory points, summary, CSV export, and desktop visualization

## Agent API

```text
POST /agent/multi/plan
POST /agent/multi/dry-run
POST /agent/multi/execute
GET  /agent/multi/runs/{run_id}
GET  /agent/multi/runs/{run_id}/export
```

## Desktop UI

The Tauri desktop app includes a **Keithley Dual** panel that drives this same
API surface:

- enter or select the 2600 and DMM6500 VISA addresses
- review the generated source and meter command previews
- run dry-run validation before touching hardware
- execute only through the confirmation-gated endpoint
- inspect captured points, summary statistics, chart, and CSV export

## Safety Rules

- Dry-run must not open VISA sessions.
- Execute requires `confirm=true`.
- Source schema must be an SMU.
- Meter schema must be a DMM.
- Source voltage and compliance must validate against the SMU schema.
- Meter function and range must validate against the DMM schema.
- Any execute failure must attempt `:OUTP OFF` on the source instrument.
- Run results must record every captured point.
- CSV export requires a completed run result.

## Future Plan

1. Add optional DMM current/resistance modes after DC voltage is stable.
2. Add experiment topology models for DUT wiring and logical signal paths.
3. Add hardware-trigger support after software synchronization is stable:
   - trigger ports in registry schemas
   - trigger edge/polarity validation
   - receiver armed state
   - DAG execution with teardown
4. Add LLM-backed structured planning that produces the same request model,
   never raw SCPI.
