"""Plan creation and validation for AI IV sweep agent workflows."""

from __future__ import annotations

import uuid

from ..api.services.sweep_service import validate_sweep_config
from ..schema import InstrumentSchema
from ..sweep import SweepConfig
from ..validator import Registry, validate_command
from .models import AgentPlan, AgentRun, AgentRunStatus, AgentValidationResult
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
