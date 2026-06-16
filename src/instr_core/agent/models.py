"""Models for AI experiment-agent planning and execution."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from ..sweep import SweepConfig


class ExperimentType(str, Enum):
    """Supported agent experiment types."""

    IV_SWEEP = "iv_sweep"
    DUAL_KEITHLEY_SWEEP = "dual_keithley_sweep"


class AgentPlanMode(str, Enum):
    """Execution mode for an agent plan."""

    DRY_RUN = "dry_run"
    EXECUTE = "execute"


class AgentRunStatus(str, Enum):
    """Lifecycle state for an agent run."""

    PLANNED = "planned"
    DRY_RUN = "dry_run"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ParsedIvSweepIntent(BaseModel):
    """Structured fields parsed from a natural-language IV sweep goal."""

    start_voltage: float
    stop_voltage: float
    step: float = Field(gt=0)
    compliance: float = Field(gt=0)
    delay_ms: int = Field(default=10, ge=0)
    direction: Literal["UP", "DOWN", "BOTH"] = "UP"

    def to_sweep_config(self) -> SweepConfig:
        """Convert parsed intent into the existing sweep config model."""
        return SweepConfig(
            start_voltage=self.start_voltage,
            stop_voltage=self.stop_voltage,
            step=self.step,
            compliance=self.compliance,
            delay_ms=self.delay_ms,
            direction=self.direction,
        )


class AgentPlan(BaseModel):
    """A structured experiment plan created by the agent layer."""

    plan_id: str
    experiment_type: ExperimentType = ExperimentType.IV_SWEEP
    mode: AgentPlanMode = AgentPlanMode.DRY_RUN
    goal: str
    instrument_key: str
    address: str
    config: SweepConfig
    commands: list[str]
    requires_confirmation: bool = True


class AgentValidationResult(BaseModel):
    """Validation result for an agent dry-run."""

    valid: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    estimated_points: int
    requires_confirmation: bool = True


class AgentRun(BaseModel):
    """Stored lifecycle state for an agent plan/run."""

    run_id: str
    plan: AgentPlan
    validation: AgentValidationResult | None = None
    status: AgentRunStatus = AgentRunStatus.PLANNED
    sweep_session_id: str | None = None
    error_message: str | None = None
    result: "DualSweepResult | None" = None


class AgentPlanRequest(BaseModel):
    """Request to create an agent plan from natural language."""

    goal: str
    instrument_key: str | None = None
    address: str | None = None


class AgentPlanResponse(BaseModel):
    """Response containing a planned agent run."""

    run: AgentRun


class AgentDryRunRequest(BaseModel):
    """Request to dry-run an existing plan."""

    run_id: str


class AgentDryRunResponse(BaseModel):
    """Response containing dry-run validation."""

    run: AgentRun


class AgentExecuteRequest(BaseModel):
    """Request to execute a validated plan."""

    run_id: str
    confirm: bool = False


class AgentExecuteResponse(BaseModel):
    """Response after starting execution."""

    run: AgentRun


class InstrumentBinding(BaseModel):
    """Bind an instrument role to an address and schema."""

    address: str
    instrument_key: str


class MeterConfig(BaseModel):
    """Configuration for the DMM in a dual-device sweep."""

    function: Literal["VOLT:DC"] = "VOLT:DC"
    range: float = Field(gt=0)


class DualKeithleyPlan(BaseModel):
    """Plan for a software-synchronized Keithley 2600 + DMM6500 sweep."""

    plan_id: str
    experiment_type: ExperimentType = ExperimentType.DUAL_KEITHLEY_SWEEP
    mode: AgentPlanMode = AgentPlanMode.DRY_RUN
    goal: str
    source: InstrumentBinding
    meter: InstrumentBinding
    source_config: SweepConfig
    meter_config: MeterConfig
    commands: dict[str, list[str]]
    requires_confirmation: bool = True


class DualSweepPoint(BaseModel):
    """One source/meter data point from a dual-device sweep."""

    source_voltage: float
    meter_value: float
    timestamp: str


class DualSweepSummary(BaseModel):
    """Summary statistics for a dual-device sweep."""

    points: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None


class DualSweepResult(BaseModel):
    """In-memory result for a dual-device sweep run."""

    points: list[DualSweepPoint] = Field(default_factory=list)
    summary: DualSweepSummary


class DualKeithleyRun(BaseModel):
    """Stored lifecycle state for a dual-device agent run."""

    run_id: str
    plan: DualKeithleyPlan
    validation: AgentValidationResult | None = None
    status: AgentRunStatus = AgentRunStatus.PLANNED
    error_message: str | None = None
    result: DualSweepResult | None = None


class DualKeithleyPlanRequest(BaseModel):
    """Request to plan a dual Keithley software-synchronized sweep."""

    goal: str
    source: InstrumentBinding
    meter: InstrumentBinding
    source_config: SweepConfig
    meter_config: MeterConfig


class DualKeithleyPlanResponse(BaseModel):
    """Response containing a dual-device run."""

    run: DualKeithleyRun


class AgentLlmPlanRequest(BaseModel):
    """Request an LLM-backed structured experiment plan."""

    goal: str
    experiment_type: Literal["dual_keithley_sweep"] = "dual_keithley_sweep"


class DualKeithleyDryRunRequest(BaseModel):
    """Request to dry-run a dual-device run."""

    run_id: str


class DualKeithleyExecuteRequest(BaseModel):
    """Request to execute a dual-device run."""

    run_id: str
    confirm: bool = False


AgentRun.model_rebuild()
