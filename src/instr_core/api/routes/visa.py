from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..dependencies import (
    _set_address_schema,
    _set_address_state,
)
from ..models import CommandRequest, CommandResponse, ConnectedInstrument
from ..services.command_preflight import CommandRejected, preflight_hardware_command
from ..services.visa_service import get_visa, update_address_state

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
    registry = request.app.state.registry
    try:
        preflight = preflight_hardware_command(
            request=request,
            address=req.address,
            raw_command=req.command,
            should_validate=req.should_validate,
            registry=registry,
        )
    except CommandRejected as exc:
        logger.warning(
            "Command preflight blocked %s to %s: %s",
            req.command,
            req.address,
            "; ".join(exc.issues),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        rm = get_visa()
        inst = rm.open_resource(req.address)

        # Send the command
        if preflight.is_query:
            resp = inst.query(req.command).strip()
        else:
            inst.write(req.command)
            resp = None

        # Update virtual state if command succeeded
        if preflight.validated and registry is not None:
            update_address_state(
                request,
                req.address,
                preflight.command,
                preflight.argument,
                registry,
            )

        return CommandResponse(
            address=req.address,
            command=req.command,
            response=resp,
            validated=preflight.validated,
            validation_issues=list(preflight.issues),
            validation_suggestions=list(preflight.suggestions),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Command failed: {exc}")


@router.get("/connected", response_model=list[ConnectedInstrument])
def list_connected_instruments() -> list[ConnectedInstrument]:
    # PyVISA does not track "connected" state; we return empty for now.
    # Future: maintain an in-memory session registry.
    return []
