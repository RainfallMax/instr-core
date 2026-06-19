from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import _get_address_schema, get_registry
from ..models import ValidateRequest, ValidateResponse
from ..services.visa_service import split_command_argument
from ...validator import validate_command

router = APIRouter(tags=["validate"])


@router.post("/validate/command", response_model=ValidateResponse)
def validate_command_endpoint(
    req: ValidateRequest,
    request: Request,
    registry=Depends(get_registry),
) -> ValidateResponse:
    """Validate a command against the instrument's schema.

    Unlike /visa/command which requires a hardware connection,
    this endpoint works purely from the schema registry.
    """
    # Determine schema key: explicit instrument key takes precedence
    schema_key: str | None = None
    if req.instrument is not None:
        schema_key = req.instrument
    elif req.address is not None:
        schema_key = _get_address_schema(request, req.address)

    if schema_key is None:
        return ValidateResponse(
            instrument=req.instrument,
            address=req.address,
            command=req.command,
            argument=req.argument,
            valid=False,
            issues=["No schema available for validation"],
            suggestions=[
                "Connect the instrument or provide explicit instrument key"
            ],
        )

    try:
        schema = registry.get_schema(schema_key)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument '{schema_key}' not found in registry"
        )

    # Auto-split command/argument if argument not explicitly provided
    command_str, argument = req.command, req.argument
    if argument is None:
        command_str, argument = split_command_argument(req.command)

    state = req.current_state or {}
    result = validate_command(schema, command_str, argument, state)
    return ValidateResponse(
        instrument=schema_key,
        address=req.address,
        command=command_str,
        argument=argument,
        valid=result.valid,
        issues=result.issues,
        suggestions=result.suggestions,
    )
