# Architecture: IV Sweep 数据采集与绘图

> 架构设计文档 | instr-core v0.3.0 | 基于 PRD_IVSWEEP.md

---

## 1. 技术栈选择

### 1.1 后端

| 组件 | 技术 | 理由 |
|------|------|------|
| HTTP API | FastAPI (现有) | 与现有 api_server.py 共享框架，无需引入新运行时 |
| 数据模型 | Pydantic v2 (现有) | 与现有 schema.py 共享类型系统 |
| 扫描执行 | Python `threading.Thread` + `queue.Queue` | 扫描是阻塞式硬件I/O，需要后台线程避免阻塞HTTP worker。`queue`用于线程安全的数据传递 |
| VISA通信 | PyVISA (现有) | 复用现有 `_get_visa()` 机制 |
| CSV导出 | Python `csv` 标准库 | 无需外部依赖 |
| 状态持久化 | 内存 (in-memory dict) | v0.3.x 不实现磁盘持久化。扫描会话保存在 `_sweep_sessions: dict[str, SweepSession]` |

### 1.2 前端

| 组件 | 技术 | 理由 |
|------|------|------|
| UI框架 | React 18 (现有) | 复用现有技术栈 |
| 图表绘制 | 原生 SVG | I-V曲线是最简单的折线图，SVG `<path>` + `<circle>` 即可。零依赖、包体积小、完全可控。未来如需复杂图表再引入 Chart.js |
| 状态管理 | React `useState` / `useReducer` | 扫描状态相对简单，不需要引入 Redux/Zustand |
| 样式 | 现有 App.css | 复用暗色主题 |
| 通信 | `fetch` + 轮询 | v0.3.x MVP 选择轮询而非 WebSocket，降低复杂度。每 200ms 轮询一次进度 |

### 1.3 未选择的技术及原因

| 候选 | 未选择原因 |
|------|-----------|
| WebSocket / SSE | 需要额外连接管理和错误恢复，对于 v0.3.x 轮询足够。v0.4.x 可考虑升级 |
| Chart.js / Recharts | 包体积大（Chart.js ~200KB gzipped），功能过剩。SVG原生绘制 I-V 折线图足够 |
| Web Workers | 前端计算量极小，不需要 |
| SQLite / 文件持久化 | v0.3.x 明确不做磁盘持久化 |

---

## 2. 模块划分

### 2.1 后端模块

```
src/instr_core/
├── sweep/
│   ├── __init__.py           # 导出 public API
│   ├── models.py             # SweepConfig, SweepPoint, SweepResult, SweepSession Pydantic模型
│   └── engine.py             # SweepEngine 类：后台线程执行扫描，线程安全状态管理
├── api_server.py             # 新增 /sweep/* endpoints（修改现有文件）
└── ... (existing files)
```

**`sweep/models.py`** 职责：
- 定义所有扫描相关的 Pydantic 数据模型
- 与 `schema.py` 中的 `GlobalLimits` 联动进行参数验证

**`sweep/engine.py`** 职责：
- `SweepEngine` 类：封装扫描执行逻辑
- 在后台线程中运行扫描序列
- 通过 `queue.Queue` 将实时数据点推送到主线程
- 管理扫描生命周期（IDLE → RUNNING → COMPLETED/ABORTED/ERROR）
- 确保 `:OUTP OFF` 在任何终止路径上被执行

**`api_server.py` 新增** 职责：
- `POST /sweep/start` — 接收 SweepConfig，启动扫描，返回 session_id
- `GET /sweep/{session_id}/status` — 返回当前扫描状态 + 已采集数据点
- `POST /sweep/{session_id}/stop` — 请求停止扫描
- `GET /sweep/{session_id}/result` — 返回完整扫描结果
- `GET /sweep/{session_id}/export` — 返回 CSV 下载
- `GET /sweep/history` — 返回所有历史扫描会话列表

### 2.2 前端模块

```
desktop/src/
├── components/
│   ├── ... (existing components)
│   └── sweep/
│       ├── IvSweepPanel.tsx       # 主面板：布局协调器
│       ├── SweepConfigForm.tsx    # 扫描参数配置表单
│       ├── SweepChart.tsx         # SVG 实时 I-V 曲线图
│       ├── SweepDataTable.tsx     # 实时数据表格
│       └── SweepHistory.tsx       # 历史扫描列表
├── types.ts                       # 新增 Sweep 相关类型
└── App.tsx                        # 新增 "IV Sweep" tab
```

**`IvSweepPanel.tsx`** 职责：
- 扫描状态机管理（IDLE / RUNNING / COMPLETED / ABORTED / ERROR）
- 轮询逻辑（200ms 间隔调用 `/sweep/{id}/status`）
- 数据收集（将实时点追加到数组）
- 子组件编排：ConfigForm + Chart + DataTable + History

**`SweepConfigForm.tsx`** 职责：
- 表单输入（Start/Stop/Step/Compliance/Delay/Direction）
- 实时参数验证（调用 `/validate/command` 预览参数合法性）
- Start/Stop 按钮状态控制

**`SweepChart.tsx`** 职责：
- 纯展示组件，接收 `SweepPoint[]` 数据
- SVG 渲染：坐标轴、网格线、I-V 折线、数据点
- 自动缩放（根据数据范围调整坐标轴）
- 正向/反向扫描用不同颜色

**`SweepDataTable.tsx`** 职责：
- 接收 `SweepPoint[]`，展示两列表格
- 新行追加动画（可选）
- 支持清空

**`SweepHistory.tsx`** 职责：
- 显示内存中的历史扫描列表
- 点击历史项加载数据和图表
- 显示点数和完成时间

---

## 3. 数据流

### 3.1 扫描启动流

```
Frontend                          Backend
   │                                 │
   │ POST /sweep/start               │
   │ {config}                       ─┼─▶ api_server.py
   │                                 │    ├─▶ validate config against schema
   │                                 │    ├─▶ create SweepSession
   │                                 │    ├─▶ SweepEngine.start(session)
   │         {session_id}           ◀┼─   └─▶ return session_id
   │◀────────────────────────────────│
   │                                 │
   │ GET /sweep/{id}/status (poll)   │
   │────────────────────────────────▶│
   │         {status, data[]}       ◀┼─▶ SweepEngine.get_status()
   │◀────────────────────────────────│
   │        (repeat every 200ms)     │
```

### 3.2 实时数据流（后端内部）

```
SweepEngine (background thread)
    │
    ├──▶ PyVISA write/read
    │       │
    │       └──▶ {voltage, current}
    │
    ├──▶ queue.put(SweepPoint)
    │
    └──▶ (thread loop continues)

Main Thread (FastAPI worker)
    │
    ├──▶ queue.get_nowait()  (drain all available points)
    │
    └──▶ update SweepSession.data
```

### 3.3 前端状态流

```
IvSweepPanel state:
    sweepId: string | null
    status: "idle" | "running" | "completed" | "aborted" | "error"
    points: SweepPoint[]
    error: string | null
    progress: {current: number, total: number}

useEffect (polling):
    if status === "running" and sweepId:
        interval = setInterval(async () => {
            const res = await fetch(`/sweep/${sweepId}/status`)
            const data = await res.json()
            setPoints(prev => [...prev, ...data.newPoints])
            setStatus(data.status)
            setProgress(data.progress)
        }, 200)
        return () => clearInterval(interval)
```

---

## 4. 关键设计决策

### 4.1 为什么用后台线程而非 asyncio？

PyVISA 的 `query()` 是同步阻塞调用。如果用 `asyncio`，需要在线程池中运行 PyVISA 操作，增加了复杂性。直接使用 `threading.Thread` 更简单，且 FastAPI 的同步 endpoint 可以自然等待线程完成。

### 4.2 为什么用轮询而非 WebSocket？

- **实现复杂度**：轮询只需要现有 HTTP 基础设施，WebSocket 需要额外的连接管理和错误恢复
- **可靠性**：轮询在每个请求上是独立的，不会因连接断开而丢失状态
- **足够实时**：200ms 轮询间隔对于 IV Sweep（每点几十到几百毫秒）完全足够
- **未来升级路径**：v0.4.x 可以平滑升级到 SSE 或 WebSocket，API 契约保持不变

### 4.3 为什么用 SVG 而非图表库？

- **零依赖**：不增加 bundle 体积
- **完全可控**：可以精确匹配暗色主题
- **足够简单**：I-V 曲线是最基础的折线图
- **性能**：1000 个 SVG `<circle>` 在现代浏览器中性能足够
- **增量更新**：新点到达时只需追加一个 `<circle>` 和更新 `<path>` 的 `d` 属性

### 4.4 扫描参数验证策略

三层验证：
1. **前端表单验证**：基本的数值范围（>0, 非空等）
2. **后端 Pydantic 验证**：类型检查、范围检查
3. **Schema 验证**：每个参数调用 `validate_command` 检查仪器约束

第3层是 instr-core 的核心价值——确保扫描参数不会损坏硬件。

---

## 5. 文件目录树（完整）

```
instr-core/
├── docs/
│   ├── PRD_IVSWEEP.md
│   └── Architecture_IVSWEEP.md   ← 本文档
│
├── src/instr_core/
│   ├── __init__.py
│   ├── schema.py                  # (现有) Pydantic模型
│   ├── validator.py               # (现有) 验证引擎
│   ├── registry_client.py         # (现有) 远程Schema拉取
│   ├── server.py                  # (现有) MCP Server
│   ├── main.py                    # (现有) MCP CLI入口
│   ├── api_server.py              # (修改) 新增 /sweep/* endpoints
│   ├── idn_parser.py              # (现有) IDN解析
│   └── sweep/                     # (新增)
│       ├── __init__.py
│       ├── models.py              # SweepConfig, SweepPoint, SweepResult, SweepSession
│       └── engine.py              # SweepEngine 后台线程执行
│
├── desktop/src/
│   ├── main.tsx                   # (现有) React入口
│   ├── App.tsx                    # (修改) 新增 IV Sweep tab
│   ├── App.css                    # (修改) 新增 Sweep样式
│   ├── types.ts                   # (修改) 新增 Sweep类型
│   └── components/
│       ├── (existing components)
│       └── sweep/                 # (新增)
│           ├── IvSweepPanel.tsx   # 主面板
│           ├── SweepConfigForm.tsx# 配置表单
│           ├── SweepChart.tsx     # SVG图表
│           ├── SweepDataTable.tsx # 数据表格
│           └── SweepHistory.tsx   # 历史列表
│
├── tests/
│   ├── (existing tests)
│   └── test_sweep.py              # (新增) Sweep引擎单元测试
│
└── tests/fixtures/registry/
    └── (existing fixtures)
```

---

## 6. API 契约

### 6.1 POST /sweep/start

Request:
```json
{
  "instrument_key": "keithley/smu/2600",
  "address": "USB0::0x05E6::0x2600::INSTR",
  "config": {
    "start_voltage": 0.0,
    "stop_voltage": 20.0,
    "step": 0.5,
    "compliance": 0.01,
    "delay_ms": 10,
    "direction": "UP"
  }
}
```

Response (200):
```json
{
  "session_id": "swp-abc123",
  "status": "running",
  "total_points": 41
}
```

Response (400):
```json
{
  "detail": "Validation failed: start_voltage 50 exceeds max 40.0"
}
```

### 6.2 GET /sweep/{session_id}/status

Response (200):
```json
{
  "session_id": "swp-abc123",
  "status": "running",
  "progress": {"current": 15, "total": 41},
  "new_points": [
    {"voltage": 7.0, "current": 1.5e-6, "timestamp": "2026-06-05T10:30:01.234Z"}
  ]
}
```

### 6.3 POST /sweep/{session_id}/stop

Response (200):
```json
{
  "session_id": "swp-abc123",
  "status": "aborted"
}
```

### 6.4 GET /sweep/{session_id}/export

Response: `text/csv` 文件下载

### 6.5 GET /sweep/history

Response (200):
```json
{
  "sessions": [
    {
      "session_id": "swp-abc123",
      "instrument_key": "keithley/smu/2600",
      "status": "completed",
      "points_count": 41,
      "created_at": "2026-06-05T10:30:00Z",
      "completed_at": "2026-06-05T10:30:05Z"
    }
  ]
}
```

---

## 7. 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| PyVISA 通信超时导致扫描僵死 | 中 | 高 | engine 中设置 read_timeout，超时后标记 ERROR 并发送 `:OUTP OFF` |
| 扫描线程泄漏（未正确 join） | 低 | 中 | 使用 `threading.Event` 作为停止信号，确保线程可优雅退出 |
| 前端轮询导致服务器压力 | 低 | 低 | 200ms 间隔足够稀疏；v0.4.x 可升级到 SSE |
| 大量数据点导致 SVG 性能下降 | 中 | 中 | >1000 点时考虑数据降采样（显示每 N 个点）|
| 内存中历史记录无限增长 | 低 | 中 | 限制保留最近 20 次扫描，自动丢弃最旧的 |
