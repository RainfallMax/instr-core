# AGENTS.md — instr-core

本文件约束 AI 在操作 `instr-core` 项目时的行为。

`instr-core` 是一个轻量级的 Python 核心库，作为 AI 操作硬件的"代理人"和"物理防火墙"。它通过 MCP 接口向 AI 暴露验证工具，运行时从远端 `instr-registry` 动态拉取 YAML Schema，并使用 Pydantic 强类型化后拦截并验证硬件控制指令。

**从 v0.2.0 起，项目增加了 Tauri 桌面应用。** 桌面应用与 MCP Server 共享同一个 Python 验证引擎，但增加了 FastAPI HTTP 服务层，供 React UI 调用。

---

## 1. 项目定位与架构

### 1.1 双运行时架构

```
┌─────────────────────────────────────────────────────────────┐
│                        instr-core                            │
├──────────────────────────────────────┬──────────────────────┤
│           MCP 工作流                  │      桌面工作流       │
├──────────────────────────────────────┼──────────────────────┤
│  AI (Claude/Cursor)                  │  Tauri (Rust + React)│
│    ↓ stdio MCP                       │    ↓ HTTP localhost  │
│  main.py → server.py                 │  api_server.py       │
│    ↓                                 │    ↓                 │
│  validator.py ←── 共享 ──→ validator.py                    │
│    ↓                                 │    ↓                 │
│  RegistryClient / 本地 YAML          │  Registry + PyVISA   │
│    ↓                                 │    ↓                 │
│  AI 生成代码                         │  UI 手动控制仪器      │
└──────────────────────────────────────┴──────────────────────┘
```

- **MCP Server** (`main.py` + `server.py`)：通过 stdio 与 AI 助手通信，AI 在代码生成前调用验证工具。
- **桌面后端** (`api_server.py`)：通过 HTTP 与 React UI 通信，提供仪器发现、SCPI 发送、状态查询。
- **两者共享**：`validator.py`（验证引擎）、`schema.py`（Pydantic 模型）、`Registry`（Schema 加载缓存）。

### 1.2 模块职责

| 模块 | 职责 | 所属工作流 |
|------|------|-----------|
| `schema.py` | Pydantic 数据模型，定义 YAML 的结构化契约。修改前需确认与 `instr-registry` 中现有 YAML 的兼容性。 | 共享 |
| `registry_client.py` | 远端拉取 YAML 并管理本地缓存。HTTP 超时 30s，失败时抛出 `RuntimeError`。 | 共享 |
| `validator.py` | 验证引擎（核心防火墙逻辑）。任何新增校验规则必须通过 `tests/test_validator.py` 的单元测试。 | 共享 |
| `server.py` | FastMCP 服务（tools、prompts、resources）。新增 tool 必须配置 `ToolAnnotations`。 | MCP |
| `main.py` | MCP CLI 入口。支持 `--registry` 本地目录覆盖和 `--registry-url` 自定义远端地址。 | MCP |
| `api_server.py` | FastAPI HTTP 服务。为桌面 UI 暴露 REST API。新增 endpoint 需考虑 CORS（允许 `localhost:1420`）。 | 桌面 |

### 1.3 数据流向

**MCP 工作流：**
```
AI 请求 → server.py tool handler → validator.py → 返回文本结果给 AI
```

**桌面工作流：**
```
React UI fetch → api_server.py endpoint → validator.py / PyVISA → 返回 JSON 给 UI
```

---

## 2. 代码开发约束

### 2.1 Schema 变更流程

若需要扩展 YAML 契约（如新增 `hardware_topology` 或 `standard_workflows` 字段）：

1. 先在 `instr-core/src/instr_core/schema.py` 中补充对应的 Pydantic 模型。
2. 更新 `instr-registry/CLAUDE.md`，让社区知道新字段已可用。
3. 在 `instr-registry` 中提交包含新字段的示例 YAML。
4. 最后更新 `instr-core` 的验证逻辑和测试。

**顺序不可颠倒**：先改代码契约，再改数据文档，最后改数据实例。

### 2.2 安全优先原则

- 验证逻辑必须**保守**（宁可误报，不可漏报）。
- 任何涉及 `output ON`、大功率输出、模式切换的校验规则，默认应要求最严格的前置条件。
- 新增校验规则时，必须在 `validator.py` 中提供对应的 `suggestions`（指导 AI 如何修复）。
- 桌面端发送的 SCPI 命令**同样**要经过 `validator.py` 校验，不允许 UI 绕过安全层。

### 2.3 代码规范

- 遵循 `.ruff.toml`：`line-length = 100`，`target-version = "py312"`。
- 使用 `from __future__ import annotations` 保持前向兼容的类型注解。
- 所有公共函数和类必须带有类型注解和 docstring。
- 前端代码（React/TypeScript）遵循 `desktop/tsconfig.json` 的严格模式。

---

## 3. YAML 数据来源

AI **不应**在 `instr-core` 中创建或修改仪器 YAML 文件。如需新增仪器描述：

1. 在独立的 `instr-registry` 仓库中创建 YAML 文件。
2. 遵循 `instr-registry/CLAUDE.md` 中的 YAML 规范。
3. 通过 Pull Request 提交到 `instr-registry`。

`instr-core` 通过以下 URL 模式拉取远端数据：

```
https://raw.githubusercontent.com/instr-community/instr-registry/main/registry/{vendor}/{type}/{model}.yaml
```

本地缓存路径：

```
~/.instr-core/registry_cache/{vendor}/{type}/{model}.yaml
```

---

## 4. 测试

运行全部测试：

```bash
uv run pytest tests/ -v
```

关键测试文件：

- `tests/test_schema.py` — Schema 解析和字段校验
- `tests/test_validator.py` — 命令验证逻辑
- `tests/test_registry_client.py` — 远端拉取和本地缓存逻辑

桌面端测试（未来）：
- `desktop/src/__tests__/` — React 组件测试（Vitest）
- `desktop/src-tauri/src/tests/` — Rust 侧逻辑测试

---

## 5. 与 instr-registry 的协作关系

| 仓库 | 内容 | AI 约束 |
|------|------|---------|
| `instr-core` | Python 核心库（MCP Server、验证引擎、FastAPI） | 不写 YAML，不改 `registry/` 数据 |
| `instr-registry` | 纯数据仓库（YAML 仪器描述） | 不写代码，只写 YAML |

> 两个仓库通过 GitHub Raw URL 耦合：`instr-core` 在运行时从 `instr-registry` 拉取 YAML。YAML 的编写规范详见 `instr-registry/CLAUDE.md`。

---

## 6. 桌面开发规范

### 6.1 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 壳层 | Tauri v2 (Rust) | 窗口、菜单、系统托盘、进程管理 |
| 前端 | React 18 + Vite | UI 组件、状态管理、路由 |
| 通信 | HTTP REST + WebSocket | 与 Python 后端的数据交换 |
| 后端 | FastAPI + uvicorn | 请求路由、VISA 管理、验证 |
| 引擎 | Python (共享) | Schema、验证、状态追踪 |

### 6.2 通信协议

Python 后端默认监听 `localhost:8765`。前端通过 `fetch` 调用：

```typescript
const API_BASE = "http://localhost:8765";

// 获取仪器列表
fetch(`${API_BASE}/instruments`)

// 扫描 VISA 资源
fetch(`${API_BASE}/visa/resources`)

// 发送 SCPI 命令
fetch(`${API_BASE}/visa/command`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ address, command, validate: true })
})
```

CORS 已在 `api_server.py` 中配置，允许 `http://localhost:1420` 和 `tauri://localhost`。

### 6.3 进程生命周期

Tauri 的 `main.rs` 负责：
1. 启动时寻找 `api_server.py`（开发模式：相对路径；生产模式：sidecar 或 Resources）
2. 用 `uv run python` 或 `python` 启动子进程
3. 设置环境变量 `INSTR_CORE_API_PORT=8765`
4. 窗口关闭时发送 `SIGTERM` 终止 Python 进程

**AI 修改注意**：
- 不要改变端口（8765 和 1420 是硬编码约定）
- `main.rs` 中的进程查找逻辑是平台相关的，修改需测试 Windows/macOS/Linux
- Python 后端必须能独立启动（不依赖 Tauri），以便单独调试

### 6.4 文件布局

```
desktop/
├── package.json              # Node 依赖
├── vite.config.ts            # Vite 配置（端口 1420）
├── tsconfig.json             # TS 严格模式
├── index.html
└── src/
    ├── main.tsx              # React 根组件挂载
    ├── App.tsx               # 主布局
    ├── App.css               # 全局样式（暗色主题）
    └── components/           # 未来拆分 UI 组件
└── src-tauri/
    ├── Cargo.toml            # Rust 依赖
    ├── tauri.conf.json       # 窗口、安全、打包配置
    ├── build.rs              # 编译脚本
    └── src/
        ├── main.rs           # 入口：启动 Python 子进程
        └── lib.rs            # 库入口（供测试）
```

---

## 7. 路线图与优先级

**v0.2.x（当前）**
- [x] Tauri + React + Python 桌面骨架
- [x] FastAPI HTTP 服务层
- [x] 基础 SCPI 终端 UI
- [ ] VISA 资源扫描和连接
- [ ] Schema 浏览器 UI
- [ ] 实时验证反馈（命令发送前显示 issues）

**v0.3.x**
- [ ] IV sweep 数据采集和绘图
- [ ] 多仪器同步序列编辑器
- [ ] 测量数据导出（CSV / HDF5）
- [ ] 自动 instrument 检测（从 *IDN? 自动匹配 schema）

**v0.4.x**
- [ ] 仪器面板模板（示波器、源表、万用表）
- [ ] WebSocket 实时数据流
- [ ] 自动化测试记录和回放
- [ ] 生产打包（Python sidecar 嵌入 Tauri）

**AI 助手在进行开发决策时，应参考以上优先级。不要为 v0.4.x 的功能编写 v0.2.x 的代码。**
