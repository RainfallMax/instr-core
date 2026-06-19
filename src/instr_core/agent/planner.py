"""Plan creation and validation for AI IV sweep agent workflows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..api.services.sweep_service import validate_sweep_config
from ..safety import safe_turn_off_output
from ..schema import CommandDef
from ..schema import InstrumentSchema
from ..sweep import SweepConfig
from ..validator import Registry, validate_command
from .models import (
    AgentPlan,
    AgentRun,
    AgentRunStatus,
    AgentValidationResult,
    DualKeithleyPlan,
    DualKeithleyRun,
    DualSweepPoint,
    DualSweepResult,
    DualSweepSummary,
    InstrumentBinding,
    MeterConfig,
)
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
            if raw.startswith("...") or raw == "*RST":
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


def build_dual_keithley_commands(
    source_config: SweepConfig,
    meter_config: MeterConfig,
) -> dict[str, list[str]]:
    """Build command previews for the dual Keithley software-synchronized sweep."""
    max_voltage = max(abs(source_config.start_voltage), abs(source_config.stop_voltage))
    return {
        "source": [
            "*RST",
            ":OUTP OFF",
            ":SOUR:FUNC VOLT",
            f":SENS:CURR:PROT {source_config.compliance:g}",
            f":SOUR:VOLT:RANG {max_voltage:g}",
            f":SOUR:VOLT {source_config.start_voltage:g}",
            ":OUTP ON",
            "... loop: :SOUR:VOLT <point> ...",
            ":OUTP OFF",
        ],
        "meter": [
            ":CONF:VOLT:DC",
            f":SENS:VOLT:DC:RANG {meter_config.range:g}",
            "... loop: :READ? ...",
        ],
    }


def create_dual_keithley_run(
    goal: str,
    source: InstrumentBinding,
    meter: InstrumentBinding,
    source_config: SweepConfig,
    meter_config: MeterConfig,
) -> DualKeithleyRun:
    """Create a planned dual Keithley software-synchronized sweep."""
    plan = DualKeithleyPlan(
        plan_id=f"plan-{uuid.uuid4().hex[:8]}",
        goal=goal,
        source=source,
        meter=meter,
        source_config=source_config,
        meter_config=meter_config,
        commands=build_dual_keithley_commands(source_config, meter_config),
    )
    return DualKeithleyRun(run_id=f"run-{uuid.uuid4().hex[:8]}", plan=plan)


def dry_run_dual_keithley_plan(run: DualKeithleyRun, registry: Registry) -> DualKeithleyRun:
    """Validate a dual-device plan without opening VISA resources."""
    issues: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    source_schema = registry.try_get_schema(run.plan.source.instrument_key)
    meter_schema = registry.try_get_schema(run.plan.meter.instrument_key)

    if source_schema is None:
        issues.append(f"Source instrument '{run.plan.source.instrument_key}' not found")
    elif source_schema.instrument.category != "smu":
        issues.append("Source instrument must use an SMU schema")
    else:
        try:
            validate_sweep_config(run.plan.source_config, source_schema)
        except ValueError as exc:
            issues.append(f"source config: {exc}")
        _validate_command_preview(
            source_schema,
            run.plan.commands["source"],
            issues,
            suggestions,
            skip_unknown={"*RST"},
        )

    if meter_schema is None:
        issues.append(f"Meter instrument '{run.plan.meter.instrument_key}' not found")
    elif meter_schema.instrument.category != "dmm":
        issues.append("Meter instrument must use a DMM schema")
    else:
        _validate_command_preview(
            meter_schema,
            run.plan.commands["meter"],
            issues,
            suggestions,
            skip_unknown=set(),
        )
        meter_range = validate_command(
            meter_schema,
            ":SENS:VOLT:DC:RANG",
            f"{run.plan.meter_config.range:g}",
            {"function": "VOLT:DC"},
        )
        if not meter_range.valid:
            issues.extend(f"meter config: {issue}" for issue in meter_range.issues)
            suggestions.extend(meter_range.suggestions)

    run.validation = AgentValidationResult(
        valid=not issues,
        issues=issues,
        warnings=warnings,
        suggestions=suggestions,
        commands=run.plan.commands["source"] + run.plan.commands["meter"],
        estimated_points=estimate_points(run.plan.source_config),
        requires_confirmation=True,
    )
    run.status = AgentRunStatus.DRY_RUN
    return run


def ensure_dual_executable(run: DualKeithleyRun, confirm: bool) -> None:
    """Raise unless a dual-device run is ready for execution."""
    if not confirm:
        raise ValueError("Execution requires confirm=true")
    if run.validation is None:
        raise ValueError("Run must be dry-run before execution")
    if not run.validation.valid:
        raise ValueError("Cannot execute an invalid dry-run")


def execute_dual_keithley_run(run: DualKeithleyRun, visa_manager: Any) -> DualKeithleyRun:
    """Execute a software-synchronized 2600 + DMM6500 sweep."""
    source = visa_manager.open_resource(run.plan.source.address)
    meter = visa_manager.open_resource(run.plan.meter.address)
    points: list[DualSweepPoint] = []
    execution_error: Exception | None = None

    try:
        meter.write(":CONF:VOLT:DC")
        meter.write(f":SENS:VOLT:DC:RANG {run.plan.meter_config.range:g}")

        source.write("*RST")
        source.write(":OUTP OFF")
        source.write(":SOUR:FUNC VOLT")
        source.write(f":SENS:CURR:PROT {run.plan.source_config.compliance:g}")
        max_voltage = max(
            abs(run.plan.source_config.start_voltage),
            abs(run.plan.source_config.stop_voltage),
        )
        source.write(f":SOUR:VOLT:RANG {max_voltage:g}")
        source.write(f":SOUR:VOLT {run.plan.source_config.start_voltage:g}")
        source.write(":OUTP ON")

        for voltage in _generate_voltage_points(run.plan.source_config):
            source.write(f":SOUR:VOLT {voltage:g}")
            raw = meter.query(":READ?").strip()
            meter_value = float(raw.split(",")[0].strip())
            points.append(
                DualSweepPoint(
                    source_voltage=voltage,
                    meter_value=meter_value,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
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
        raise RuntimeError(
            "Sweep completed but source output could not be confirmed off"
        )

    values = [point.meter_value for point in points]
    summary = DualSweepSummary(
        points=len(points),
        min=min(values) if values else None,
        max=max(values) if values else None,
        mean=sum(values) / len(values) if values else None,
    )
    run.result = DualSweepResult(points=points, summary=summary)
    run.status = AgentRunStatus.COMPLETED
    return run


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


def _validate_command_preview(
    schema: InstrumentSchema,
    commands: list[str],
    issues: list[str],
    suggestions: list[str],
    skip_unknown: set[str],
) -> None:
    state: dict[str, str] = {}
    for raw in commands:
        if raw.startswith("..."):
            continue
        if raw in skip_unknown:
            continue
        command, argument = _split_preview_command(raw)
        result = validate_command(schema, command, argument, state)
        if not result.valid and not raw.endswith("?"):
            issues.extend(result.issues)
            suggestions.extend(result.suggestions)
        _apply_schema_state(schema, command, argument, state)


def _apply_schema_state(
    schema: InstrumentSchema,
    command: str,
    argument: str | None,
    state: dict[str, str],
) -> None:
    cmd_def: CommandDef | None = next((c for c in schema.commands if c.command == command), None)
    if cmd_def is None:
        _apply_preview_state(command, argument, state)
        return
    for key, template in cmd_def.sets_state.items():
        if template == "$ARGUMENT":
            value = argument
        elif template == "$ARGUMENT_UPPER":
            value = argument.upper() if argument is not None else None
        else:
            value = template
        if value is not None:
            state[key] = value


def _generate_voltage_points(config: SweepConfig) -> list[float]:
    n_steps = int(round(abs(config.stop_voltage - config.start_voltage) / config.step))
    if config.start_voltage <= config.stop_voltage:
        points = [round(config.start_voltage + i * config.step, 12) for i in range(n_steps + 1)]
    else:
        points = [round(config.start_voltage - i * config.step, 12) for i in range(n_steps + 1)]
    if points:
        points[-1] = config.stop_voltage
    if config.direction == "DOWN":
        return list(reversed(points))
    if config.direction == "BOTH":
        down = list(reversed(points))
        return points + down[1:]
    return points
