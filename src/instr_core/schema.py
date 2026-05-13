"""Pydantic models for instrument schema definitions loaded from YAML."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _coerce_bool(v: object) -> object:
    """PyYAML 1.1 parses ON/OFF/YES/NO as booleans. Coerce them back to strings."""
    if isinstance(v, bool):
        return "ON" if v else "OFF"
    return v


StrOrBool = Annotated[str, BeforeValidator(_coerce_bool)]


class InstrumentInfo(BaseModel):
    """Basic instrument identification."""

    manufacturer: str
    model: str
    series: str | None = None
    category: str | None = None
    description: str | None = None
    firmware_version: str | None = None
    doc_source: str | None = None


class LimitDef(BaseModel):
    """A single numeric safety limit with its unit."""

    max: float
    unit: str


class GlobalLimits(BaseModel):
    """Hard safety limits for the instrument as a whole.

    Limits are keyed by physical quantity (voltage, current, power, etc.).
    The schema author decides which quantities are relevant for the
    instrument category; the engine only checks limits that are declared.

    All three fields are optional so non-SMU instruments can express
    themselves honestly: oscilloscopes typically have no output-power
    limit, DMMs have no source-current limit, spectrum analysers have
    no source-voltage limit. When a field is ``None`` the engine
    silently skips the corresponding global-limit check; per-command
    ``range`` constraints still apply.
    """

    voltage: LimitDef | None = None
    current: LimitDef | None = None
    power: LimitDef | None = None


class ParameterDef(BaseModel):
    """A parameter within a command."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    param_type: str = Field(alias="type")
    allowed_values: list[StrOrBool] = Field(default_factory=list)


class Range(BaseModel):
    """Numeric range constraint (min, max inclusive)."""

    min: float
    max: float


class SequenceRule(BaseModel):
    """A sequencing rule (e.g., 'compliance must be set before output ON')."""

    before: str | None = None
    after: str | None = None
    require_state_keys_present: list[str] = Field(default_factory=list)
    expect_state: dict[str, StrOrBool] = Field(default_factory=dict)
    message: str


class Safety(BaseModel):
    """Safety-related metadata for a command."""

    compliance_required: bool | None = None
    compliance_parameter: str | None = None
    sequence: list[SequenceRule] = Field(default_factory=list)


class CommandDef(BaseModel):
    """A single SCPI command definition with its constraints."""

    model_config = ConfigDict(populate_by_name=True)

    command: str
    description: str | None = None
    parameters: list[ParameterDef] = Field(default_factory=list)
    range: Range | None = None
    requires: dict[str, StrOrBool] = Field(default_factory=dict)
    forbidden_when: dict[str, StrOrBool] = Field(default_factory=dict)
    safety: Safety | None = None
    sets_state: dict[str, StrOrBool] = Field(default_factory=dict)


class InstrumentSchema(BaseModel):
    """Top-level instrument schema loaded from a YAML file."""

    version: str = Field(default="1.0.0")
    instrument: InstrumentInfo
    global_limits: GlobalLimits
    commands: list[CommandDef]
