from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..dependencies import (
    _get_address_schema,
    _get_address_state,
    _set_address_schema,
    _set_address_state,
)
from ..models import CommandRequest, CommandResponse, ConnectedInstrument
from ..services.visa_service import get_visa, split_command_argument, update_address_state
from ...validator import validate_command

logger = logging.getLogger("instr_core.api")

router = APIRouter(prefix="/visa", tags=["visa"])


@router.get("/resources", response_model=list[str])
def list_visa_resources() -> list[str]:
    try:
        rm = get_visa()
        return list(rm.list_resources())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/connect")
def connect_instrument(request: Request, address: str) -> ConnectedInstrument:
    try:
        rm = get_visa()
        inst = rm.open_resource(address)
        idn = inst.query("*IDN?").strip()
        parts = idn.split(",")

        # Parse IDN and look up schema key from registry
        schema_key: str | None = None
        registry = request.app.state.registry
        if registry is not None:
            try:
                from ...idn_parser import parse_idn
                idn_info = parse_idn(idn)
                schema_key = registry.find_schema_by_idn(idn_info)
                if schema_key:
                    logger.info(
                        "Auto-mapped address %s to schema %s", address, schema_key
                    )
            except Exception as exc:
                logger.warning("Failed to lookup schema for %s: %s", address, exc)

        # Store mapping for later validation
        _set_address_schema(request, address, schema_key)
        # Initialize empty state for this address
        _set_address_state(request, address, {})

        return ConnectedInstrument(
            address=address,
            manufacturer=parts[0] if len(parts) > 0 else None,
            model=parts[1] if len(parts) > 1 else None,
            serial=parts[2] if len(parts) > 2 else None,
            idn=idn,
            schema_key=schema_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to connect: {exc}")


@router.post("/command", response_model=CommandResponse)
def send_command_endpoint(request: Request, req: CommandRequest) -> CommandResponse:
    try:
        rm = get_visa()
        inst = rm.open_resource(req.address)

        # Validation layer
        issues: list[str] = []
        suggestions: list[str] = []
        validated = False

        registry = request.app.state.registry
        if req.should_validate and registry is not None:
            schema_key = _get_address_schema(request, req.address)
            if schema_key is not None:
                validated = True
                state = _get_address_state(request, req.address) or {}
                schema = registry.try_get_schema(schema_key)
                if schema is not None:
                    command_str, argument = split_command_argument(req.command)

                    result = validate_command(
                        schema,
                        command_str,
                        argument,
                        state,
                    )
                    issues = result.issues
                    suggestions = result.suggestions

                    # If validation failed and it's a write command (not query),
                    # block the command as a safety measure.
                    is_query = req.command.strip().endswith("?")
                    if not result.valid and not is_query:
                        logger.warning(
                            "Validation blocked write command %s to %s: %s",
                            req.command,
                            req.address,
                            "; ".join(result.issues),
                        )
                        return CommandResponse(
                            address=req.address,
                            command=req.command,
                            error=f"VALIDATION BLOCKED: {'; '.join(result.issues)}",
                            validated=True,
                            validation_issues=result.issues,
                            validation_suggestions=result.suggestions,
                        )

        # Send the command
        if req.command.strip().endswith("?"):
            resp = inst.query(req.command).strip()
        else:
            inst.write(req.command)
            resp = None

        # Update virtual state if command succeeded
        if validated and not issues:
            command_str, argument = split_command_argument(req.command)
            update_address_state(request, req.address, command_str, argument, registry)

        return CommandResponse(
            address=req.address,
            command=req.command,
            response=resp,
            validated=validated,
            validation_issues=issues,
            validation_suggestions=suggestions,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Command failed: {exc}")


@router.get("/connected", response_model=list[ConnectedInstrument])
def list_connected_instruments() -> list[ConnectedInstrument]:
    # PyVISA does not track "connected" state; we return empty for now.
    # Future: maintain an in-memory session registry.
    return []
