from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..dependencies import (
    get_address_ownership,
    get_registry,
    get_sweep_engine,
    get_visa_sessions,
)
from ..models import (
    SweepStartRequest,
    SweepStartResponse,
    SweepStatusResponse,
    SweepHistoryItem,
)
from ..services.sweep_service import validate_sweep_config
from ...sweep import SweepSession, SweepStatus
from ..services.session_manager import SessionNotFound, SessionUnhealthy

logger = logging.getLogger("instr_core.api")

router = APIRouter(prefix="/sweep", tags=["sweep"])


@router.post("/start", response_model=SweepStartResponse)
def sweep_start(
    req: SweepStartRequest,
    request: Request,
    registry=Depends(get_registry),
    sweep_engine=Depends(get_sweep_engine),
    ownership=Depends(get_address_ownership),
    visa_sessions=Depends(get_visa_sessions),
) -> SweepStartResponse:
    """Start a new IV sweep session."""
    # 1. Validate instrument_key exists in registry
    if req.instrument_key not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument '{req.instrument_key}' not found in registry"
        )

    # 2. Load schema
    try:
        schema = registry.get_schema(req.instrument_key)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument '{req.instrument_key}' not found in registry"
        )

    # 3. Validate SweepConfig against schema
    try:
        validate_sweep_config(req.config, schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Validation failed: {exc}")

    # 4. Validate address is connected (has schema mapping)
    from ..dependencies import _get_address_schema
    if _get_address_schema(request, req.address) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Address '{req.address}' is not connected. "
                   "Call /visa/connect first."
        )

    # 5. Create SweepSession
    session_id = f"swp-{uuid.uuid4().hex[:8]}"
    session = SweepSession(
        session_id=session_id,
        instrument_key=req.instrument_key,
        address=req.address,
        config=req.config,
        status=SweepStatus.IDLE,
    )

    if not ownership.acquire(req.address, session_id):
        raise HTTPException(
            status_code=409,
            detail=f"Address '{req.address}' is already owned by an active operation",
        )

    try:
        visa_sessions.get(req.address)
    except (SessionNotFound, SessionUnhealthy) as exc:
        ownership.release(req.address, session_id)
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    # 7. Start sweep in background thread
    try:
        sweep_engine.start_sweep(
            session,
            registry,
            visa_sessions.lease(req.address),
            on_complete=lambda completed: _complete_managed_sweep(
                completed,
                visa_sessions,
                ownership,
                req.address,
                session_id,
            ),
        )
    except Exception as exc:
        ownership.release(req.address, session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start sweep: {exc}"
        )

    # 8. Calculate total points (round-trip via integer steps for fp safety)
    n_steps = int(round(abs(req.config.stop_voltage - req.config.start_voltage) / req.config.step))
    total_points = n_steps + 1

    logger.info(
        "Sweep %s started for %s on %s (%d points)",
        session_id,
        req.instrument_key,
        req.address,
        total_points,
    )

    return SweepStartResponse(
        session_id=session_id,
        status=SweepStatus.RUNNING.value,
        total_points=total_points,
    )


def _complete_managed_sweep(
    session: SweepSession,
    visa_sessions,
    ownership,
    address: str,
    owner: str,
) -> None:
    if session.status == SweepStatus.ERROR and session.error_message:
        visa_sessions.mark_unhealthy(address, session.error_message)
    ownership.release(address, owner)


@router.get("/{session_id}/status", response_model=SweepStatusResponse)
def sweep_status(
    session_id: str,
    since_index: int = 0,
    sweep_engine=Depends(get_sweep_engine),
) -> SweepStatusResponse:
    """Get the current status of a sweep session."""
    session = sweep_engine.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )

    n_steps = int(round(abs(session.config.stop_voltage - session.config.start_voltage) / session.config.step))
    total_points = n_steps + 1

    progress = {
        "current": len(session.points),
        "total": total_points,
    }

    # Validate and clamp since_index
    since_index = max(0, since_index)
    since_index = min(since_index, len(session.points))

    # Return only new points
    new_points = [p.model_dump() for p in session.points[since_index:]]

    return SweepStatusResponse(
        session_id=session_id,
        status=session.status.value,
        progress=progress,
        new_points=new_points,
        error_message=session.error_message,
    )


@router.post("/{session_id}/stop")
def sweep_stop(
    session_id: str,
    sweep_engine=Depends(get_sweep_engine),
) -> dict[str, Any]:
    """Request to stop a running sweep."""
    session = sweep_engine.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )

    try:
        sweep_engine.stop_sweep(session_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )

    return {
        "session_id": session_id,
        "status": session.status.value,
    }


@router.get("/{session_id}/result")
def sweep_result(
    session_id: str,
    sweep_engine=Depends(get_sweep_engine),
) -> dict[str, Any]:
    """Get the complete result of a sweep session."""
    session = sweep_engine.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )

    return {
        "session_id": session_id,
        "instrument_key": session.instrument_key,
        "address": session.address,
        "config": session.config.model_dump(),
        "status": session.status.value,
        "points": [p.model_dump() for p in session.points],
        "error_message": session.error_message,
        "created_at": session.created_at,
        "completed_at": session.completed_at,
    }


@router.get("/{session_id}/export")
def sweep_export(
    session_id: str,
    request: Request,
    sweep_engine=Depends(get_sweep_engine),
) -> StreamingResponse:
    """Export sweep results as a CSV file."""
    session = sweep_engine.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )

    # Get instrument metadata for filename
    registry = request.app.state.registry
    manufacturer = "Unknown"
    model = "Unknown"
    if registry is not None:
        meta = registry.get_metadata(session.instrument_key)
        if meta:
            manufacturer = meta.get("manufacturer", "Unknown")
            model = meta.get("model", "Unknown")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"IV_{manufacturer}_{model}_{timestamp}.csv"

    # Generate CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Voltage(V)", "Current(A)", "Timestamp"])
    for point in session.points:
        writer.writerow([
            f"{point.voltage:.6f}",
            f"{point.current:.6e}",
            point.timestamp,
        ])

    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/history")
def sweep_history(
    sweep_engine=Depends(get_sweep_engine),
) -> dict[str, Any]:
    """List recent sweep sessions (up to 20)."""
    sessions = sweep_engine.list_sessions()
    # Limit to 20 most recent
    sessions = sessions[:20]

    history = [
        SweepHistoryItem(
            session_id=s.session_id,
            instrument_key=s.instrument_key,
            status=s.status.value,
            points_count=len(s.points),
            created_at=s.created_at,
            completed_at=s.completed_at,
        )
        for s in sessions
    ]

    return {"sessions": [h.model_dump() for h in history]}
