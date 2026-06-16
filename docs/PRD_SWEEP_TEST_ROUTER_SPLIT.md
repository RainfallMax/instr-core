# PRD: Sweep Engine Testing + Backend Router Split

> 产品需求文档 | instr-core v0.3.1 | 2026-06-06

---

## 1. 功能概述

本次迭代包含两个独立但互补的目标：

**目标A — Sweep 引擎测试覆盖**：为 `sweep/engine.py` 编写全面的单元测试，确保扫描逻辑的正确性、线程安全和异常处理。当前该模块完全无测试，是发布前的最大风险点。

**目标B — 后端路由拆分**：将 `api_server.py`（875行）拆分为独立的 FastAPI 路由模块，改善可维护性和可扩展性。

---

## 2. 目标A: Sweep 引擎测试覆盖

### 2.1 测试范围

| 测试类 | 覆盖方法 | 测试场景 |
|--------|---------|---------|
| `TestGenerateVoltagePoints` | `_generate_voltage_points` | UP/DOWN/BOTH方向、浮点精度、边界值 |
| `TestSweepEngineLifecycle` | `start_sweep`, `stop_sweep`, `get_session` | 正常启动、重复启动、停止、获取状态 |
| `TestSweepEngineThreadSafety` | `start_sweep` + 并发读取 | 多线程同时读取session.points |
| `TestSafeTurnOffOutput` | `_safe_turn_off_output` | 一次成功、第一次失败第二次成功、全部失败 |
| `TestRunSweepMock` | `_run_sweep` (mock visa) | 正常扫描、中途停止、异常路径 |

### 2.2 详细测试场景

#### `_generate_voltage_points`

| 场景 | 输入 | 期望输出 |
|------|------|---------|
| UP, start < stop | start=0, stop=10, step=2.5, UP | [0, 2.5, 5.0, 7.5, 10.0] |
| UP, start > stop (auto-swap) | start=10, stop=0, step=2.5, UP | [0, 2.5, 5.0, 7.5, 10.0] |
| DOWN | start=0, stop=10, step=2.5, DOWN | [10.0, 7.5, 5.0, 2.5, 0] |
| BOTH | start=0, stop=5, step=2.5, BOTH | [0, 2.5, 5.0, 2.5, 0]（去重端点） |
| 浮点精度 | start=0, stop=1, step=0.1, UP | 11个点，最后一个精确为1.0 |
| 大量点 | start=0, stop=100, step=0.01, UP | 10001点（触发10,000上限已在models验证） |
| 单点 | start=5, stop=5, step=1, UP | [5.0] |

#### `_safe_turn_off_output`

| 场景 | Mock visa行为 | 期望日志 |
|------|--------------|---------|
| 一次成功 | 第一次write返回None | INFO: succeeded |
| 第一次失败第二次成功 | 第一次抛异常，第二次正常 | WARNING(失败) → INFO(成功) |
| 全部失败 | 三次write均抛异常 | WARNING(2次) → CRITICAL |

#### `_run_sweep` (mock visa)

| 场景 | Mock visa行为 | 期望结果 |
|------|--------------|---------|
| 正常扫描（3点） | query返回"1.23e-6" | 3个SweepPoint，status=COMPLETED |
| 多值返回 | query返回"1.23e-6,5.0,0.001,0" | 取第一个值，3个SweepPoint |
| 中途停止 | 第2点后_stop_event被设置 | 2个SweepPoint，status=ABORTED |
| 异常路径 | 第2点query抛异常 | 1个SweepPoint，status=ERROR，:OUTP OFF被调用 |
| 超时恢复 | query前timeout=3000，查询后恢复 | timeout恢复到原始值 |

### 2.3 Mock 策略

使用 Python `unittest.mock.MagicMock` 模拟 PyVISA Resource：

```python
class MockVisaResource:
    def __init__(self, responses=None):
        self._responses = responses or {}
        self._written = []
        self.timeout = 3000

    def write(self, cmd):
        self._written.append(cmd)
        if cmd in self._responses.get("write_fail", []):
            raise Exception("Write failed")

    def query(self, cmd):
        if cmd in self._responses:
            return self._responses[cmd]
        return "1.23e-6"
```

### 2.4 验收标准

- [ ] `test_sweep_engine.py` 文件创建，包含至少 5 个测试类
- [ ] 所有测试可通过 `pytest tests/test_sweep_engine.py -v`
- [ ] 覆盖率：`_generate_voltage_points` 100%，`_safe_turn_off_output` 100%，`_run_sweep` 核心路径 80%+
- [ ] 线程安全测试：10 个线程同时读取 session.points，不抛出异常

---

## 3. 目标B: 后端路由拆分

### 3.1 当前问题

`api_server.py` 875 行，包含：
- 16 个 Pydantic 模型定义（~175 行）
- 4 个工具函数（`_get_visa`, `_split_command_argument`, `_update_address_state`, 等）（~100 行）
- 10 个现有 endpoint（health, instruments, visa, validate）（~300 行）
- 6 个 sweep endpoint（~250 行）
- 全局状态管理（~50 行）

### 3.2 目标结构

```
src/instr_core/
├── api_server.py              # 入口 + app factory + lifespan（< 200 行）
├── api/
│   ├── __init__.py            # 导出 create_api_app
│   ├── dependencies.py        # FastAPI Depends: get_registry, get_sweep_engine
│   ├── models.py              # 所有 Pydantic request/response 模型
│   ├── routes/
│   │   ├── __init__.py        # 聚合所有 routers
│   │   ├── instruments.py     # /instruments/*, /instruments/{key}/safety-limits, /instruments/{key}/commands
│   │   ├── visa.py            # /visa/resources, /visa/connect, /visa/command, /visa/connected
│   │   ├── validate.py        # /validate/command
│   │   └── sweep.py           # /sweep/* (6个endpoint)
│   └── services/
│       ├── visa_service.py    # _get_visa, _split_command_argument, _update_address_state
│       └── sweep_service.py   # _validate_sweep_config
```

### 3.3 拆分原则

| 原则 | 说明 |
|------|------|
| 零行为变更 | 所有 API endpoint 的 URL、方法、请求/响应格式保持不变 |
| 零导入变更 | `api_server.py` 的导入路径保持向后兼容（如 `from .api_server import create_api_app`） |
| FastAPI router | 每个路由文件使用 `APIRouter`，在 `api_server.py` 中 `app.include_router()` |
| 依赖注入 | 全局状态（registry, sweep_engine）通过 `FastAPI Depends` 传递，而非模块级变量 |
| 服务层 | 仪器特定逻辑（如 `_validate_sweep_config`）下沉到 `services/` |

### 3.4 依赖注入设计

```python
# api/dependencies.py
from fastapi import Request

def get_registry(request: Request) -> Registry:
    return request.app.state.registry

def get_sweep_engine(request: Request) -> SweepEngine:
    return request.app.state.sweep_engine

def get_address_schema(request: Request, address: str) -> str | None:
    with request.app.state.address_lock:
        return request.app.state.address_to_schema.get(address)
```

```python
# api_server.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.registry = Registry.load(...)
    app.state.sweep_engine = SweepEngine()
    app.state.address_lock = threading.RLock()
    app.state.address_to_schema = {}
    app.state.address_state = {}
    yield
```

### 3.5 验收标准

- [ ] `api_server.py` < 200 行（当前 875 行）
- [ ] 所有现有 endpoint 可通过 `pytest tests/test_api_server.py -v`
- [ ] `test_integration.py` 的 MCP 集成测试不受影响
- [ ] `uv run python src/instr_core/api_server.py` 正常启动
- [ ] 新增模块均有类型注解和 docstring

---

## 4. 执行顺序

由于两个目标独立，可并行执行：

```
Phase 3A: Sweep引擎测试
  └─→ test_sweep_engine.py

Phase 3B: 后端路由拆分
  └─→ api/models.py
  └─→ api/dependencies.py
  └─→ api/routes/*.py
  └─→ api/services/*.py
  └─→ api_server.py (重写)
```

---

## 5. 非功能需求

- **向后兼容**：所有 URL、请求/响应格式不变
- **无新依赖**：不引入新的 Python 包
- **类型安全**：所有新增模块通过 mypy 检查（如有）
- **文档**：每个路由模块顶部有 docstring 说明其负责的 endpoint
