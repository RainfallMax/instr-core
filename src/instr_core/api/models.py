from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..sweep import SweepConfig


class CommandRequest(BaseModel):
    """Send a raw SCPI command to a connected instrument."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    command: str
    should_validate: bool = Field(default=True, alias="validate")


class CommandResponse(BaseModel):
    """Result of sending a SCPI command."""

    address: str
    command: str
    response: str | None = None
    error: str | None = None
    validated: bool = False
    validation_issues: list[str] = []
    validation_suggestions: list[str] = []


class ValidateRequest(BaseModel):
    """Validate a SCPI command against the instrument schema."""

    instrument: str | None = None
    address: str | None = None
    command: str
    argument: str | None = None
    current_state: dict[str, str] | None = None


class ValidateResponse(BaseModel):
    """Validation result."""

    instrument: str | None = None
    address: str | None = None
    command: str
    argument: str | None = None
    valid: bool
    issues: list[str]
    suggestions: list[str]


class SequenceStep(BaseModel):
    """A single step in a command sequence for validation."""

    command: str
    argument: str | None = None
    state: dict[str, str] | None = None


class ValidateSequenceRequest(BaseModel):
    """Validate a full command sequence."""

    instrument: str
    steps: list[SequenceStep]


class InstrumentMeta(BaseModel):
    """Lightweight instrument metadata for the UI list."""

    key: str
    manufacturer: str
    model: str
    description: str | None = None


class InstrumentDetail(BaseModel):
    """Full instrument schema for the UI detail view."""

    model_config = ConfigDict(populate_by_name=True)

    key: str
    instrument_schema: dict[str, Any] = Field(alias="schema")


class SafetyLimitsResponse(BaseModel):
    """Global safety limits for an instrument."""

    instrument: str
    voltage: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    power: dict[str, Any] | None = None
    frequency: dict[str, Any] | None = None


class ConnectedInstrument(BaseModel):
    """A PyVISA-connected instrument."""

    address: str
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    idn: str | None = None
    schema_key: str | None = None


class SweepStartRequest(BaseModel):
    """Request to start an IV sweep."""

    instrument_key: str
    address: str
    config: SweepConfig


class SweepStartResponse(BaseModel):
    """Response after starting a sweep."""

    session_id: str
    status: str
    total_points: int


class SweepStatusResponse(BaseModel):
    """Current status of a sweep session."""

    session_id: str
    status: str
    progress: dict[str, int]
    new_points: list[dict]
    error_message: str | None = None


class SweepHistoryItem(BaseModel):
    """Summary of a sweep session for the history list."""

    session_id: str
    instrument_key: str
    status: str
    points_count: int
    created_at: str
    completed_at: str | None = None
