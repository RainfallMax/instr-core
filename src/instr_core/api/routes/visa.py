from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import (
    _clear_address_tracking,
    _set_address_schema,
    _set_address_state,
    get_address_ownership,
    get_visa_sessions,
)
from ..models import (
    CommandRequest,
    CommandResponse,
    ConnectedInstrument,
    EmergencyStopResponse,
    EmergencyStopResult,
)
from ..services.command_preflight import CommandRejected, preflight_hardware_command
from ..services.session_manager import (
    SessionCloseError,
    SessionConnectError,
    SessionNotFound,
    SessionUnhealthy,
    VisaSessionManager,
)
from ..services.visa_service import get_visa, update_address_state
from ...safety import safe_turn_off_output

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
def connect_instrument(
    request: Request,
    address: str,
    sessions: VisaSessionManager = Depends(get_visa_sessions),
) -> ConnectedInstrument:
    def identify(candidate_address: str, inst) -> ConnectedInstrument:
        idn = inst.query("*IDN?").strip()
        parts = idn.split(",")
        schema_key: str | None = None
        registry = request.app.state.registry
        if registry is not None:
            try:
                from ...idn_parser import parse_idn

                idn_info = parse_idn(idn)
                schema_key = registry.find_schema_by_idn(idn_info)
                if schema_key:
                    logger.info(
                        "Auto-mapped address %s to schema %s",
                        candidate_address,
                        schema_key,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to lookup schema for %s: %s",
                    candidate_address,
                    exc,
                )
        return ConnectedInstrument(
            address=candidate_address,
            manufacturer=parts[0] if len(parts) > 0 else None,
            model=parts[1] if len(parts) > 1 else None,
            serial=parts[2] if len(parts) > 2 else None,
            idn=idn,
            schema_key=schema_key,
        )

    try:
        session = sessions.connect(address, identify)
        _set_address_schema(request, address, session.instrument.schema_key)
        _set_address_state(request, address, {})
        return session.instrument
    except SessionConnectError as exc:
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

    sessions = get_visa_sessions(request)
    try:
        with sessions.lease(req.address) as inst:
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
    except (SessionNotFound, SessionUnhealthy) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Command failed: {exc}")


@router.get("/connected", response_model=list[ConnectedInstrument])
def list_connected_instruments(
    sessions: VisaSessionManager = Depends(get_visa_sessions),
) -> list[ConnectedInstrument]:
    return sessions.list_connected()


def _reject_owned_address(ownership, address: str) -> None:
    if address in ownership.snapshot():
        raise HTTPException(
            status_code=409,
            detail=f"Address '{address}' is owned by an active operation",
        )


@router.post("/disconnect", response_model=ConnectedInstrument)
def disconnect_instrument(
    request: Request,
    address: str,
    ownership=Depends(get_address_ownership),
    sessions: VisaSessionManager = Depends(get_visa_sessions),
) -> ConnectedInstrument:
    _reject_owned_address(ownership, address)
    try:
        instrument = sessions.disconnect(address)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionCloseError as exc:
        _clear_address_tracking(request, address)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _clear_address_tracking(request, address)
    return instrument


@router.post("/reconnect", response_model=ConnectedInstrument)
def reconnect_instrument(
    request: Request,
    address: str,
    ownership=Depends(get_address_ownership),
    sessions: VisaSessionManager = Depends(get_visa_sessions),
) -> ConnectedInstrument:
    _reject_owned_address(ownership, address)
    try:
        try:
            sessions.disconnect(address)
        except SessionNotFound:
            pass
        _clear_address_tracking(request, address)
        return connect_instrument(request, address, sessions)
    except SessionCloseError as exc:
        _clear_address_tracking(request, address)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/emergency-stop", response_model=EmergencyStopResponse)
def emergency_stop(
    ownership=Depends(get_address_ownership),
    sessions: VisaSessionManager = Depends(get_visa_sessions),
) -> EmergencyStopResponse:
    """Attempt emergency teardown for every actively owned address."""
    results: list[EmergencyStopResult] = []
    for address, operation_id in ownership.snapshot().items():
        try:
            with sessions.lease(address) as resource:
                report = safe_turn_off_output(resource, operation_id, address)
            result = EmergencyStopResult(
                address=address,
                operation_id=operation_id,
                safe=report.safe,
                attempted_commands=list(report.attempted_commands),
                successful_command=report.successful_command,
                errors=list(report.errors),
            )
        except Exception as exc:
            logger.critical(
                "%s: emergency stop could not access %s: %s",
                operation_id,
                address,
                exc,
            )
            result = EmergencyStopResult(
                address=address,
                operation_id=operation_id,
                safe=False,
                attempted_commands=[],
                errors=[str(exc)],
            )
        results.append(result)
        if result.safe:
            ownership.release(address, operation_id)

    return EmergencyStopResponse(
        all_safe=all(result.safe for result in results),
        results=results,
    )
