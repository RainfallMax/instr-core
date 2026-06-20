from __future__ import annotations

import csv
import io
from contextlib import ExitStack
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...agent import (
    AgentDryRunRequest,
    AgentDryRunResponse,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentLlmPlanRequest,
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
from ...agent.context import build_validation_context, validation_context_fingerprint
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
from ...run_lifecycle import RunStatus, transition_run
from ..dependencies import (
    _get_all_address_states,
    _get_address_schema,
    get_address_ownership,
    get_agent_store,
    get_llm_planner,
    get_registry,
    get_sweep_engine,
    get_visa_sessions,
)
from ..services.session_manager import SessionNotFound, SessionUnhealthy

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
    request: Request,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
    visa_sessions=Depends(get_visa_sessions),
) -> AgentDryRunResponse:
    """Validate an agent plan without touching VISA."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")
    run = dry_run_plan(run, registry)
    context = build_validation_context(
        run,
        registry,
        visa_sessions,
        _get_all_address_states(request),
    )
    run.validation_context_fingerprint = validation_context_fingerprint(context)
    run.validated_at = datetime.now(timezone.utc).isoformat()
    store.update(run)
    return AgentDryRunResponse(run=run)


@router.post("/execute", response_model=AgentExecuteResponse)
def execute(
    req: AgentExecuteRequest,
    store: AgentRunStore = Depends(get_agent_store),
    registry=Depends(get_registry),
    sweep_engine=Depends(get_sweep_engine),
    ownership=Depends(get_address_ownership),
    visa_sessions=Depends(get_visa_sessions),
) -> AgentExecuteResponse:
    """Execute a validated agent plan after explicit confirmation."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")

    try:
        ensure_executable(run, req.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not ownership.acquire(run.plan.address, run.run_id):
        raise HTTPException(
            status_code=409,
            detail=f"Address '{run.plan.address}' is already owned by an active operation",
        )

    try:
        visa_sessions.get(run.plan.address)
        session = SweepSession(
            session_id=f"swp-{run.run_id.removeprefix('run-')}",
            instrument_key=run.plan.instrument_key,
            address=run.plan.address,
            config=run.plan.config,
            status=SweepStatus.IDLE,
        )
        sweep_engine.start_sweep(
            session,
            registry,
            visa_sessions.lease(run.plan.address),
            on_complete=lambda completed: _complete_agent_sweep(
                completed,
                visa_sessions,
                ownership,
                run.plan.address,
                run.run_id,
            ),
        )
    except (SessionNotFound, SessionUnhealthy) as exc:
        ownership.release(run.plan.address, run.run_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        ownership.release(run.plan.address, run.run_id)
        run.status = AgentRunStatus.FAILED
        run.error_message = str(exc)
        store.update(run)
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc

    run.status = AgentRunStatus.RUNNING
    run.sweep_session_id = session.session_id
    store.update(run)
    return AgentExecuteResponse(run=run)


def _complete_agent_sweep(
    session: SweepSession,
    visa_sessions,
    ownership,
    address: str,
    owner: str,
) -> None:
    if session.status == SweepStatus.ERROR and session.error_message:
        visa_sessions.mark_unhealthy(address, session.error_message)
    ownership.release(address, owner)


@router.get("/runs")
def list_runs(
    store: AgentRunStore = Depends(get_agent_store),
) -> dict[str, list[dict[str, object]]]:
    """Return lightweight summaries of stored agent runs."""
    runs = []
    for run in store.list():
        plan = run.plan
        runs.append(
            {
                "run_id": run.run_id,
                "experiment_type": plan.experiment_type,
                "status": run.status,
                "goal": plan.goal,
                "has_validation": run.validation is not None,
                "has_result": run.result is not None,
            }
        )
    return {"runs": runs}


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


@router.post("/llm/plan", response_model=DualKeithleyPlanResponse)
def create_llm_plan(
    req: AgentLlmPlanRequest,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
    planner=Depends(get_llm_planner),
) -> DualKeithleyPlanResponse:
    """Create a structured plan from an LLM-produced request object."""
    if planner is None:
        raise HTTPException(status_code=503, detail="LLM structured planner is not configured")
    try:
        structured = planner.plan_dual_keithley(req.goal)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM planning failed: {exc}") from exc

    if registry.try_get_schema(structured.source.instrument_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source instrument '{structured.source.instrument_key}' not found",
        )
    if registry.try_get_schema(structured.meter.instrument_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Meter instrument '{structured.meter.instrument_key}' not found",
        )
    run = create_dual_keithley_run(
        structured.goal,
        structured.source,
        structured.meter,
        structured.source_config,
        structured.meter_config,
    )
    store.create(run)
    return DualKeithleyPlanResponse(run=run)


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
    request: Request,
    registry=Depends(get_registry),
    store: AgentRunStore = Depends(get_agent_store),
    visa_sessions=Depends(get_visa_sessions),
) -> DualKeithleyPlanResponse:
    """Validate a dual-device plan without touching VISA."""
    run = store.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{req.run_id}' not found")
    if not isinstance(run, DualKeithleyRun):
        raise HTTPException(status_code=400, detail=f"Run '{req.run_id}' is not a multi run")
    run = dry_run_dual_keithley_plan(run, registry)
    context = build_validation_context(
        run,
        registry,
        visa_sessions,
        _get_all_address_states(request),
    )
    run.validation_context_fingerprint = validation_context_fingerprint(context)
    run.validated_at = datetime.now(timezone.utc).isoformat()
    store.update(run)
    return DualKeithleyPlanResponse(run=run)


@router.post("/multi/execute", response_model=DualKeithleyPlanResponse)
def execute_multi(
    req: DualKeithleyExecuteRequest,
    store: AgentRunStore = Depends(get_agent_store),
    ownership=Depends(get_address_ownership),
    visa_sessions=Depends(get_visa_sessions),
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

    addresses = [run.plan.source.address, run.plan.meter.address]
    if not ownership.acquire_many(addresses, run.run_id):
        raise HTTPException(
            status_code=409,
            detail="One or more instrument addresses are already owned",
        )

    try:
        try:
            transition_run(run, RunStatus.RUNNING)
            for address in addresses:
                visa_sessions.get(address)
            with ExitStack() as stack:
                resources = {
                    address: stack.enter_context(visa_sessions.lease(address))
                    for address in sorted(addresses)
                }
                run = execute_dual_keithley_run(
                    run,
                    resources[run.plan.source.address],
                    resources[run.plan.meter.address],
                )
        except (SessionNotFound, SessionUnhealthy) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            if run.status == RunStatus.RUNNING:
                transition_run(run, RunStatus.ERROR, reason=str(exc))
            run.error_message = str(exc)
            store.update(run)
            raise HTTPException(
                status_code=500,
                detail=f"Execution failed: {exc}",
            ) from exc
    finally:
        ownership.release_many(addresses, run.run_id)
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
