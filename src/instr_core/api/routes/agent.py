from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...agent import (
    AgentDryRunRequest,
    AgentDryRunResponse,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentParseError,
    AgentPlanRequest,
    AgentPlanResponse,
    AgentRunStatus,
    DualKeithleyDryRunRequest,
    DualKeithleyExecuteRequest,
    DualKeithleyPlanRequest,
    DualKeithleyPlanResponse,
    DualKeithleyRun,
)
from ...agent.planner import (
    create_dual_keithley_run,
    create_iv_sweep_run,
    dry_run_dual_keithley_plan,
    dry_run_plan,
    ensure_dual_executable,
    ensure_executable,
    execute_dual_keithley_run,
)
from ...agent.store import AgentRunStore
from ...sweep import SweepSession, SweepStatus
from ..dependencies import _get_address_schema, get_agent_store, get_registry, get_sweep_engine
from ..services.visa_service import get_visa

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/plan", response_model=AgentPlanResponse)
def create_plan(
    req: AgentPlanRequest,
    request: Request,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
) -> AgentPlanResponse:
    """Create an IV sweep agent plan from natural language."""
    address = req.address
    if address is None:
        raise HTTPException(status_code=400, detail="address is required for IV sweep planning")

    instrument_key = req.instrument_key or _get_address_schema(request, address)
    if instrument_key is None:
        raise HTTPException(
            status_code=400,
            detail="address is not connected to a known instrument schema",
        )
    if registry.try_get_schema(instrument_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument '{instrument_key}' not found in registry",
        )

    try:
        run = create_iv_sweep_run(req.goal, instrument_key, address)
    except AgentParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.create(run)
    return AgentPlanResponse(run=run)


@router.post("/dry-run", response_model=AgentDryRunResponse)
def dry_run(
    req: AgentDryRunRequest,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
) -> AgentDryRunResponse:
    """Validate an agent plan without touching VISA."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")
    run = dry_run_plan(run, registry)
    store.update(run)
    return AgentDryRunResponse(run=run)


@router.post("/execute", response_model=AgentExecuteResponse)
def execute(
    req: AgentExecuteRequest,
    store: AgentRunStore = Depends(get_agent_store),
    registry=Depends(get_registry),
    sweep_engine=Depends(get_sweep_engine),
) -> AgentExecuteResponse:
    """Execute a validated agent plan after explicit confirmation."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")

    try:
        ensure_executable(run, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        visa_resource = get_visa().open_resource(run.plan.address)
        session = SweepSession(
            session_id=f"swp-{run.run_id.removeprefix('run-')}",
            instrument_key=run.plan.instrument_key,
            address=run.plan.address,
            config=run.plan.config,
            status=SweepStatus.IDLE,
        )
        sweep_engine.start_sweep(session, registry, visa_resource)
    except Exception as exc:
        run.status = AgentRunStatus.FAILED
        run.error_message = str(exc)
        store.update(run)
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc

    run.status = AgentRunStatus.RUNNING
    run.sweep_session_id = session.session_id
    store.update(run)
    return AgentExecuteResponse(run=run)


@router.get("/runs/{run_id}", response_model=AgentPlanResponse)
def get_run(
    run_id: str,
    store: AgentRunStore = Depends(get_agent_store),
) -> AgentPlanResponse:
    """Return a stored agent run."""
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return AgentPlanResponse(run=run)


@router.post("/multi/plan", response_model=DualKeithleyPlanResponse)
def create_multi_plan(
    req: DualKeithleyPlanRequest,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
) -> DualKeithleyPlanResponse:
    """Create a dual Keithley software-synchronized sweep plan."""
    if registry.try_get_schema(req.source.instrument_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source instrument '{req.source.instrument_key}' not found",
        )
    if registry.try_get_schema(req.meter.instrument_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Meter instrument '{req.meter.instrument_key}' not found",
        )
    run = create_dual_keithley_run(
        req.goal,
        req.source,
        req.meter,
        req.source_config,
        req.meter_config,
    )
    store.create(run)
    return DualKeithleyPlanResponse(run=run)


@router.post("/multi/dry-run", response_model=DualKeithleyPlanResponse)
def dry_run_multi(
    req: DualKeithleyDryRunRequest,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
) -> DualKeithleyPlanResponse:
    """Validate a dual-device plan without touching VISA."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")
    if not isinstance(run, DualKeithleyRun):
        raise HTTPException(status_code=400, detail=f"Run '{req.run_id}' is not a multi run")
    run = dry_run_dual_keithley_plan(run, registry)
    store.update(run)
    return DualKeithleyPlanResponse(run=run)


@router.post("/multi/execute", response_model=DualKeithleyPlanResponse)
def execute_multi(
    req: DualKeithleyExecuteRequest,
    store: AgentRunStore = Depends(get_agent_store),
) -> DualKeithleyPlanResponse:
    """Execute a confirmed dual-device software-synchronized sweep."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")
    if not isinstance(run, DualKeithleyRun):
        raise HTTPException(status_code=400, detail=f"Run '{req.run_id}' is not a multi run")
    try:
        ensure_dual_executable(run, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        run = execute_dual_keithley_run(run, get_visa())
    except Exception as exc:
        run.status = AgentRunStatus.FAILED
        run.error_message = str(exc)
        store.update(run)
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc
    store.update(run)
    return DualKeithleyPlanResponse(run=run)


@router.get("/multi/runs/{run_id}", response_model=DualKeithleyPlanResponse)
def get_multi_run(
    run_id: str,
    store: AgentRunStore = Depends(get_agent_store),
) -> DualKeithleyPlanResponse:
    """Return a stored dual-device run."""
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if not isinstance(run, DualKeithleyRun):
        raise HTTPException(status_code=400, detail=f"Run '{run_id}' is not a multi run")
    return DualKeithleyPlanResponse(run=run)


@router.get("/multi/runs/{run_id}/export")
def export_multi_run(
    run_id: str,
    store: AgentRunStore = Depends(get_agent_store),
) -> StreamingResponse:
    """Export a completed dual-device run as CSV."""
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if not isinstance(run, DualKeithleyRun):
        raise HTTPException(status_code=400, detail=f"Run '{run_id}' is not a multi run")
    if run.result is None:
        raise HTTPException(status_code=400, detail=f"Run '{run_id}' has no result to export")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Source Voltage(V)", "Meter Value", "Timestamp"])
    for point in run.result.points:
        writer.writerow(
            [
                f"{point.source_voltage:.6f}",
                f"{point.meter_value:.6e}",
                point.timestamp,
            ]
        )
    output.seek(0)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"DualKeithley_{run.plan.source.instrument_key.replace('/', '_')}_{timestamp}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
