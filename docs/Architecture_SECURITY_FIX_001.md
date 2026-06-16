# Architecture: 安全与正确性修复 (Security Fix Round 001)

> 架构设计文档 | instr-core v0.3.0-hotfix | 基于 PRD_SECURITY_FIX_001.md

---

## 1. 技术栈（无变化）

本次修复不涉及技术栈变更，保持现有：
- 后端：Python 3.12+, FastAPI, Pydantic v2, threading
- 前端：React 18, TypeScript, fetch API

---

## 2. 模块设计

### 2.1 SF-001: 异常时 `:OUTP OFF` 失败保护

#### 文件：`src/instr_core/sweep/engine.py`

```
sweep/engine.py
├── _run_sweep()
│   └── try/finally 结构
│       ├── except Exception:
│       │   └── _safe_turn_off_output(visa, session_id)
│       └── finally:
│           └── (existing clean shutdown)
│
└── _safe_turn_off_output(visa, session_id)  ← 新增静态方法
    ├── attempt 1: visa.write(":OUTP OFF")
    │   └── log INFO on success
    │   └── on failure:
    │       ├── log WARNING
    │       ├── sleep 0.1s
    │       └── attempt 2: visa.write(":OUTP OFF")
    │           └── log INFO on success
    │           └── on failure:
    │               ├── log WARNING
    │               └── attempt 3: visa.write("*RST")
    │                   └── log INFO on success
    │                   └── on failure:
    │                       └── log CRITICAL
```

#### 核心决策
- **不引入新依赖**：重试用 `time.sleep(0.1)`，不用 retry 库
- **不修改 public API**：`_safe_turn_off_output` 是私有方法
- **日志级别递进**：WARNING → WARNING → CRITICAL，便于监控告警

---

### 2.2 SF-002: 地址映射字典线程安全

#### 文件：`src/instr_core/api_server.py`

#### 当前结构
```python
_address_to_schema: dict[str, str | None] = {}
_address_state: dict[str, dict[str, str]] = {}
```

#### 目标结构
```python
_address_lock = threading.RLock()
_address_to_schema: dict[str, str | None] = {}
_address_state: dict[str, dict[str, str]] = {}

def _set_address_schema(address: str, schema_key: str | None) -> None:
    with _address_lock:
        _address_to_schema[address] = schema_key

def _get_address_schema(address: str) -> str | None:
    with _address_lock:
        return _address_to_schema.get(address)

def _get_all_address_schemas() -> dict[str, str | None]:
    with _address_lock:
        return dict(_address_to_schema)  # shallow copy snapshot

def _set_address_state(address: str, state: dict[str, str]) -> None:
    with _address_lock:
        _address_state[address] = state

def _get_address_state(address: str) -> dict[str, str] | None:
    with _address_lock:
        s = _address_state.get(address)
        return dict(s) if s is not None else None  # shallow copy snapshot

def _update_address_state_entry(address: str, key: str, value: str) -> None:
    with _address_lock:
        if address not in _address_state:
            _address_state[address] = {}
        _address_state[address][key] = value
```

#### 影响范围
| 原代码 | 替换为 |
|--------|--------|
| `_address_to_schema[address] = schema_key` | `_set_address_schema(address, schema_key)` |
| `_address_to_schema.get(address)` | `_get_address_schema(address)` |
| `_address_state[address] = {}` | `_set_address_state(address, {})` |
| `_address_state.get(address, {})` | `_get_address_state(address)` or `{}` |
| `_address_state.setdefault(address, {})[key] = value` | `_update_address_state_entry(address, key, value)` |

#### 核心决策
- **RLock 而非 Lock**：允许嵌套获取（如读取时触发写入）
- **快照返回**：读取方法返回字典副本，调用方无需持有锁即可迭代
- **浅拷贝足够**：字典的值是字符串（不可变），浅拷贝即安全

---

### 2.3 SF-003: VisaResourcePanel 错误处理

#### 文件：`desktop/src/components/VisaResourcePanel.tsx`

#### 当前结构
```typescript
const connectInstrument = async (address: string) => {
    const res = await fetch(...);
    const data = await res.json();
    onConnect(data);
};
```

#### 目标结构
```typescript
const [error, setError] = useState<string | null>(null);
const [connecting, setConnecting] = useState<string | null>(null);

const connectInstrument = async (address: string) => {
    setConnecting(address);
    setError(null);
    try {
        const res = await fetch(...);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Connection failed (${res.status})`);
        }
        const data: ConnectedInstrument = await res.json();
        onConnect(data);
    } catch (err) {
        const msg = err instanceof Error ? err.message : "Connection failed";
        setError(`${address}: ${msg}`);
        setTimeout(() => setError(null), 5000);
    } finally {
        setConnecting(null);
    }
};
```

#### UI 变化
- 每个 VISA 资源项的 Connect 按钮在 `connecting === address` 时显示 "Connecting..." 并禁用
- 错误信息以红色文本显示在列表顶部或对应项下方
- 5 秒后自动清除错误信息

---

### 2.4 SF-004: Sweep 状态端点增量返回

#### 文件：`src/instr_core/api_server.py`

#### API 变更

```python
# 当前
@app.get("/sweep/{session_id}/status")
def sweep_status(session_id: str) -> SweepStatusResponse:
    ...
    new_points = [p.model_dump() for p in session.points]
    ...

# 目标
@app.get("/sweep/{session_id}/status")
def sweep_status(session_id: str, since_index: int = 0) -> SweepStatusResponse:
    ...
    # Validate since_index
    since_index = max(0, since_index)
    since_index = min(since_index, len(session.points))

    # Return only new points
    new_points = [p.model_dump() for p in session.points[since_index:]]
    ...
```

#### 前端适配

```typescript
// IvSweepPanel.tsx 轮询逻辑
const lastCountRef = useRef(0);

intervalRef.current = setInterval(async () => {
    const since = lastCountRef.current;
    const res = await fetch(`${API_BASE}/sweep/${sweepId}/status?since_index=${since}`);
    const data = await res.json();

    // 增量追加
    setPoints(prev => [...prev, ...(data.new_points || [])]);
    lastCountRef.current = since + (data.new_points?.length || 0);
    ...
}, 200);
```

#### 核心决策
- **默认 since_index=0**：不带参数时行为不变（向后兼容）
- **前端用 ref 追踪**：不用 state（避免不必要的重渲染）
- **服务器端切片**：`session.points[since_index:]` 是 O(1) 操作（Python list slicing 返回新 list，但底层数据共享）
- **索引边界检查**：`min(since_index, len(points))` 防止越界

---

## 3. 文件变更清单

| 文件 | 变更类型 | 变更内容 |
|------|---------|---------|
| `src/instr_core/sweep/engine.py` | 修改 | 新增 `_safe_turn_off_output`，替换异常处理中的 `except: pass` |
| `src/instr_core/api_server.py` | 修改 | 新增 `_address_lock` 和 6 个封装方法；修改所有字典读写；修改 `/sweep/status` 支持 `since_index` |
| `desktop/src/components/VisaResourcePanel.tsx` | 修改 | 新增 error/connecting state；检查 res.ok；显示错误提示 |
| `desktop/src/components/sweep/IvSweepPanel.tsx` | 修改 | 轮询时传递 `since_index`；增量追加数据点 |
| `tests/test_api_server.py` | 修改 | 新增 since_index 测试；新增并发安全测试 |
| `tests/test_sweep_engine.py` | 新建 | 测试 `_safe_turn_off_output`、`_generate_voltage_points` |

---

## 4. 风险评估

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| 加锁后并发性能下降 | 低 | 低 | RLock 在 FastAPI 线程池中开销极小（μs 级） |
| since_index 引入后前端数据丢失 | 低 | 中 | 用 ref 追踪，state 只追加不替换；边界检查 |
| VisaResourcePanel 错误处理引入新 bug | 低 | 低 | 保留现有成功路径，仅增加失败分支 |
| 现有测试因导入变更失败 | 中 | 中 | 修改后运行全部测试验证 |
