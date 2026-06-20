from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from fastapi import Request

from ..agent.llm import StructuredPlanner, planner_from_env
from ..agent.store import AgentRunStore
from ..sweep import SweepEngine
from ..safety import safe_turn_off_output
from ..validator import Registry
from .services.ownership_service import AddressOwnershipRegistry
from .services.session_manager import VisaSessionManager

logger = logging.getLogger("instr_core.api")


def _get_visa_resource_manager():
    """Resolve the lazy VISA manager without creating an import cycle."""
    from .services.visa_service import get_visa

    return get_visa()


def init_app_state(app) -> None:
    """Initialize application state (registry, sweep engine, address tracking)."""
    paths = _load_registry_paths()
    if paths:
        app.state.registry = Registry.load(*paths)
        logger.info("Registry loaded from %s (%d instruments)", paths, len(app.state.registry))
    else:
        logger.warning("No registry paths configured; instrument schemas unavailable.")
        app.state.registry = None

    app.state.sweep_engine = SweepEngine()
    logger.info("SweepEngine initialized")
    app.state.agent_store = AgentRunStore(run_dir=_load_agent_runs_dir())
    logger.info("AgentRunStore initialized")
    app.state.llm_planner = planner_from_env()
    logger.info("LLM structured planner configured: %s", app.state.llm_planner is not None)
    app.state.address_lock = threading.RLock()
    app.state.address_to_schema = {}
    app.state.address_state = {}
    app.state.address_ownership = AddressOwnershipRegistry()
    app.state.visa_sessions = VisaSessionManager(_get_visa_resource_manager)


def shutdown_app_state(app) -> list[str]:
    """Safely tear down owned outputs and close all managed VISA resources."""
    errors: list[str] = []
    ownership: AddressOwnershipRegistry | None = getattr(
        app.state,
        "address_ownership",
        None,
    )
    sessions: VisaSessionManager | None = getattr(
        app.state,
        "visa_sessions",
        None,
    )
    if sessions is None:
        return errors

    if ownership is not None:
        for address, operation_id in ownership.snapshot().items():
            try:
                with sessions.lease(address) as resource:
                    report = safe_turn_off_output(resource, operation_id, address)
                if report.safe:
                    ownership.release(address, operation_id)
                else:
                    errors.extend(report.errors)
            except Exception as exc:
                errors.append(f"{address}: {exc}")

    errors.extend(sessions.shutdown())
    return errors


def get_registry(request: Request) -> Registry:
    """FastAPI dependency: get the instrument registry."""
    registry = request.app.state.registry
    if registry is None:
        raise RuntimeError("Registry not loaded")
    return registry


def get_sweep_engine(request: Request) -> SweepEngine:
    """FastAPI dependency: get the sweep engine."""
    return request.app.state.sweep_engine


def get_agent_store(request: Request) -> AgentRunStore:
    """FastAPI dependency: get the agent run store."""
    return request.app.state.agent_store


def get_llm_planner(request: Request) -> StructuredPlanner | None:
    """FastAPI dependency: get the configured structured LLM planner."""
    return getattr(request.app.state, "llm_planner", None)


def get_address_ownership(request: Request) -> AddressOwnershipRegistry:
    """Get the application-wide instrument address ownership registry."""
    ownership = getattr(request.app.state, "address_ownership", None)
    if ownership is None:
        ownership = AddressOwnershipRegistry()
        request.app.state.address_ownership = ownership
    return ownership


def get_visa_sessions(request: Request) -> VisaSessionManager:
    """Get the application-wide managed VISA session registry."""
    sessions = getattr(request.app.state, "visa_sessions", None)
    if sessions is None:
        sessions = VisaSessionManager(_get_visa_resource_manager)
        request.app.state.visa_sessions = sessions
    return sessions


def _load_registry_paths() -> list[str]:
    """Load registry paths from environment or default."""
    env = os.environ.get("INSTR_CORE_REGISTRY", "")
    if env:
        return [p.strip() for p in env.replace(",", os.pathsep).split(os.pathsep) if p.strip()]
    project_root = Path(__file__).resolve().parents[3]
    default = project_root / "tests" / "fixtures" / "registry"
    if default.exists():
        return [str(default)]
    return []


def _load_agent_runs_dir() -> Path:
    """Load the agent run persistence directory from environment or default."""
    env = os.environ.get("INSTR_CORE_RUNS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".instr-core" / "runs"


# Address schema helpers


def _set_address_schema(request: Request, address: str, schema_key: str | None) -> None:
    with request.app.state.address_lock:
        request.app.state.address_to_schema[address] = schema_key


def _get_address_schema(request: Request, address: str) -> str | None:
    with request.app.state.address_lock:
        return request.app.state.address_to_schema.get(address)


def _get_all_address_schemas(request: Request) -> dict[str, str | None]:
    with request.app.state.address_lock:
        return dict(request.app.state.address_to_schema)


def _set_address_state(request: Request, address: str, state: dict[str, str]) -> None:
    with request.app.state.address_lock:
        request.app.state.address_state[address] = state


def _get_address_state(request: Request, address: str) -> dict[str, str] | None:
    with request.app.state.address_lock:
        s = request.app.state.address_state.get(address)
        return dict(s) if s is not None else None


def _update_address_state_entry(request: Request, address: str, key: str, value: str) -> None:
    with request.app.state.address_lock:
        if address not in request.app.state.address_state:
            request.app.state.address_state[address] = {}
        request.app.state.address_state[address][key] = value


def _clear_address_tracking(request: Request, address: str) -> None:
    """Remove schema and virtual-state tracking for one disconnected address."""
    with request.app.state.address_lock:
        request.app.state.address_to_schema.pop(address, None)
        request.app.state.address_state.pop(address, None)
