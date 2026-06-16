# Architecture: Sweep Engine Testing + Backend Router Split

> Architecture Design Document | instr-core v0.3.1 | Based on PRD_SWEEP_TEST_ROUTER_SPLIT.md

---

## 1. Technology Stack (No Changes)

- **Backend**: Python 3.12+, FastAPI, Pydantic v2, pytest, unittest.mock
- **Frontend**: React 18, TypeScript (not involved in this iteration)

---

## 2. Module Design

### 2.1 Goal A: Sweep Engine Testing

#### File: `tests/test_sweep_engine.py`

```
tests/test_sweep_engine.py
├── MockVisaResource
│   ├── write(cmd) → None or raise
│   ├── query(cmd) → str or raise
│   └── timeout (attribute)
│
├── TestGenerateVoltagePoints
│   ├── test_up_normal(start < stop)
│   ├── test_up_auto_swap(start > stop)
│   ├── test_down()
│   ├── test_both_no_duplicate()
│   ├── test_floating_point_precision()
│   ├── test_single_point()
│   └── test_negative_voltages()
│
├── TestSafeTurnOffOutput
│   ├── test_first_attempt_succeeds()
│   ├── test_second_attempt_succeeds()
│   ├── test_all_attempts_fail_logs_critical()
│   └── test_rst_fallback_succeeds()
│
├── TestSweepEngineLifecycle
│   ├── test_start_sweep_creates_session()
│   ├── test_start_duplicate_raises()
│   ├── test_stop_sweep_sets_event()
│   ├── test_get_session_existing()
│   ├── test_get_session_missing()
│   └── test_list_sessions_order()
│
├── TestSweepEngineThreadSafety
│   └── test_concurrent_reads_no_exception()
│
└── TestRunSweepMock
    ├── test_normal_sweep_3_points()
    ├── test_multi_value_read_response()
    ├── test_stop_mid_sweep()
    ├── test_exception_mid_sweep_output_off()
    ├── test_timeout_restored()
    └── test_points_thread_safe_append()
```

#### Key Design Decisions

- **Mock instead of patch**: Create `MockVisaResource` class instead of `unittest.mock.patch` for better control over per-command behavior
- **No real hardware**: All tests use mock visa resources
- **Thread safety test**: Spawn 10 threads reading `session.points` while main thread appends, verify no `RuntimeError`
- **Log capture**: Use `pytest.LogCaptureFixture` to verify `_safe_turn_off_output` log levels

---

### 2.2 Goal B: Backend Router Split

#### Current Structure (875 lines in `api_server.py`)

```
api_server.py
├── Pydantic models (~175 lines)
├── Global state (~50 lines)
├── Helper functions (~100 lines)
│   ├── _get_visa()
│   ├── _split_command_argument()
│   ├── _update_address_state()
│   └── _set/get_address_* (6 methods)
├── Routes (~550 lines)
│   ├── /health
│   ├── /instruments/*
│   ├── /validate/command
│   ├── /visa/*
│   └── /sweep/*
```

#### Target Structure

```
src/instr_core/
├── api_server.py              # App factory + lifespan only (< 100 lines)
│
└── api/
    ├── __init__.py            # Empty or exports
    ├── dependencies.py        # FastAPI Depends functions
    ├── models.py              # All Pydantic models (~175 lines)
    │
    ├── routes/
    │   ├── __init__.py        # Import and export routers
    │   ├── instruments.py     # /instruments/* (4 endpoints)
    │   ├── visa.py            # /visa/* (4 endpoints)
    │   ├── validate.py        # /validate/command
    │   └── sweep.py           # /sweep/* (6 endpoints)
    │
    └── services/
        ├── __init__.py
        ├── visa_service.py    # _get_visa, _split_command_argument, _update_address_state
        └── sweep_service.py   # _validate_sweep_config
```

#### `api_server.py` (Target: < 100 lines)

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

from .api.routes import instruments, visa, validate, sweep
from .api.dependencies import init_app_state

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_app_state(app)
    yield

def create_api_app() -> FastAPI:
    app = FastAPI(..., lifespan=lifespan)
    app.add_middleware(CORSMiddleware, ...)

    app.include_router(instruments.router)
    app.include_router(visa.router)
    app.include_router(validate.router)
    app.include_router(sweep.router)

    return app
```

#### `api/dependencies.py`

```python
from fastapi import Request
from .validator import Registry
from .sweep import SweepEngine

def init_app_state(app) -> None:
    app.state.registry = ...
    app.state.sweep_engine = SweepEngine()
    app.state.address_lock = threading.RLock()
    app.state.address_to_schema = {}
    app.state.address_state = {}

def get_registry(request: Request) -> Registry:
    return request.app.state.registry

def get_sweep_engine(request: Request) -> SweepEngine:
    return request.app.state.sweep_engine
```

#### `api/routes/instruments.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_registry
from ..models import InstrumentMeta, InstrumentDetail, SafetyLimitsResponse

router = APIRouter(prefix="/instruments", tags=["instruments"])

@router.get("", response_model=list[InstrumentMeta])
def list_instruments(registry = Depends(get_registry)):
    ...

@router.get("/{instrument_key}", response_model=InstrumentDetail)
def get_instrument(instrument_key: str, registry = Depends(get_registry)):
    ...

@router.get("/{instrument_key}/safety-limits", response_model=SafetyLimitsResponse)
def get_safety_limits(instrument_key: str, registry = Depends(get_registry)):
    ...

@router.get("/{instrument_key}/commands")
def get_command_tree(instrument_key: str, registry = Depends(get_registry)):
    ...
```

#### `api/routes/visa.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_registry
from ..services.visa_service import get_visa, split_command_argument, update_address_state
from ..models import CommandResponse, ConnectedInstrument, CommandRequest

router = APIRouter(prefix="/visa", tags=["visa"])
```

#### `api/routes/validate.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_registry
from ..models import ValidateRequest, ValidateResponse

router = APIRouter(tags=["validate"])

@router.post("/validate/command", response_model=ValidateResponse)
def validate_command_endpoint(req: ValidateRequest, registry = Depends(get_registry)):
    ...
```

#### `api/routes/sweep.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_registry, get_sweep_engine
from ..services.sweep_service import validate_sweep_config
from ..models import SweepStartRequest, SweepStartResponse, SweepStatusResponse

router = APIRouter(prefix="/sweep", tags=["sweep"])
```

### 2.3 Migration Plan

Phase 1 (No-deletion):
1. Create `api/` directory structure
2. Copy models to `api/models.py`
3. Create `api/dependencies.py` with `init_app_state`
4. Create route files with copied endpoint code
5. Update imports in route files to use `Depends`

Phase 2 (Verification):
6. Run all tests to ensure zero behavior change
7. Verify `api_server.py` still works as entry point

Phase 3 (Cleanup):
8. Delete old code from `api_server.py`
9. Keep only app factory + lifespan

### 2.4 Backward Compatibility

| Aspect | Guarantee |
|--------|-----------|
| URL paths | Unchanged (FastAPI router prefix preserves paths) |
| HTTP methods | Unchanged |
| Request/response schemas | Unchanged (same Pydantic models) |
| Import paths | `from instr_core.api_server import create_api_app` still works |
| CLI entry point | `uv run python src/instr_core/api_server.py` still works |
| Test imports | `from instr_core.api_server import create_api_app` still works |

---

## 3. File Change List

### New Files

| File | Lines | Description |
|------|-------|-------------|
| `tests/test_sweep_engine.py` | ~300 | Sweep engine unit tests |
| `src/instr_core/api/__init__.py` | ~5 | Package init |
| `src/instr_core/api/dependencies.py` | ~30 | FastAPI Depends + app state init |
| `src/instr_core/api/models.py` | ~175 | All Pydantic models (copied from api_server.py) |
| `src/instr_core/api/routes/__init__.py` | ~10 | Router aggregation |
| `src/instr_core/api/routes/instruments.py` | ~80 | /instruments/* endpoints |
| `src/instr_core/api/routes/visa.py` | ~150 | /visa/* endpoints |
| `src/instr_core/api/routes/validate.py` | ~40 | /validate/command endpoint |
| `src/instr_core/api/routes/sweep.py` | ~200 | /sweep/* endpoints |
| `src/instr_core/api/services/__init__.py` | ~5 | Package init |
| `src/instr_core/api/services/visa_service.py` | ~40 | VISA helper functions |
| `src/instr_core/api/services/sweep_service.py` | ~30 | Sweep validation function |

### Modified Files

| File | Change | Description |
|------|--------|-------------|
| `src/instr_core/api_server.py` | Rewrite | Reduce to ~80 lines (app factory + lifespan only) |
| `tests/test_api_server.py` | Update | Update imports if needed |

### Deleted (moved)

| From | To |
|------|-----|
| `api_server.py` models | `api/models.py` |
| `api_server.py` route handlers | `api/routes/*.py` |
| `api_server.py` helper functions | `api/services/*.py` |

---

## 4. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Circular imports during migration | Medium | High | Use lazy imports in `dependencies.py`; verify with `python -c "import instr_core.api_server"` |
| FastAPI router prefix breaks URL | Low | High | Test each endpoint with `TestClient` after migration |
| `app.state` not initialized before router access | Low | High | Ensure `lifespan` runs before any request; use `Depends` not direct access |
| Tests fail due to import changes | Medium | Medium | Run full test suite after each phase |
| Sweep engine tests flaky (timing) | Medium | Low | Use `threading.Event` not `time.sleep` in tests; mock time if needed |

---

## 5. Verification Checklist

- [ ] `python -m py_compile src/instr_core/api_server.py` passes
- [ ] `python -m py_compile src/instr_core/api/**/*.py` passes
- [ ] `pytest tests/test_sweep_engine.py -v` all pass
- [ ] `pytest tests/test_api_server.py -v` all pass
- [ ] `pytest tests/test_integration.py -v` all pass
- [ ] `pytest tests/` all pass
- [ ] `uv run python src/instr_core/api_server.py` starts without error
- [ ] `TestClient` can call all endpoints
- [ ] `api_server.py` < 100 lines
