# AGENTS.md — instr-core

本文件约束 AI 在操作 `instr-core` 项目时的行为。

`instr-core` 是一个轻量级的 Python 核心库，作为 AI 操作硬件的"代理人"和"物理防火墙"。它通过 MCP 接口向 AI 暴露验证工具，运行时从远端 `instr-registry` 动态拉取 YAML Schema，并使用 Pydantic 强类型化后拦截并验证硬件控制指令。

---

## 1. 项目定位与架构

- `instr-core` **不包含**仪器 YAML 数据。所有数据存放在独立的 `instr-registry` 仓库中。
- `instr-core` 在运行时通过 `RegistryClient` 从 GitHub Raw URL 拉取 YAML，并缓存到 `~/.instr-core/registry_cache/`。
- `instr-core` 的核心职责是：**提供 MCP Server 接口**、**运行时解析 YAML**、**拦截并验证 SCPI 命令**。

---

## 2. 代码开发约束

### 2.1 模块职责

| 模块 | 职责 |
|------|------|
| `schema.py` | Pydantic 数据模型，定义 YAML 的结构化契约。修改前需确认与 `instr-registry` 中现有 YAML 的兼容性。 |
| `registry_client.py` | 远端拉取 YAML 并管理本地缓存。HTTP 超时 30s，失败时抛出 `RuntimeError`。 |
| `validator.py` | 验证引擎（核心防火墙逻辑）。任何新增校验规则必须通过 `tests/test_validator.py` 的单元测试。 |
| `server.py` | FastMCP 服务（tools、prompts、resources）。新增 tool 必须配置 `ToolAnnotations`。 |
| `main.py` | CLI 入口。支持 `--registry` 本地目录覆盖和 `--registry-url` 自定义远端地址。 |

### 2.2 Schema 变更流程

若需要扩展 YAML 契约（如新增 `hardware_topology` 或 `standard_workflows` 字段）：

1. 先在 `instr-core/src/instr_core/schema.py` 中补充对应的 Pydantic 模型。
2. 更新 `instr-registry/CLAUDE.md`，让社区知道新字段已可用。
3. 在 `instr-registry` 中提交包含新字段的示例 YAML。
4. 最后更新 `instr-core` 的验证逻辑和测试。

**顺序不可颠倒**：先改代码契约，再改数据文档，最后改数据实例。

### 2.3 安全优先原则

- 验证逻辑必须**保守**（宁可误报，不可漏报）。
- 任何涉及 `output ON`、大功率输出、模式切换的校验规则，默认应要求最严格的前置条件。
- 新增校验规则时，必须在 `validator.py` 中提供对应的 `suggestions`（指导 AI 如何修复）。

### 2.4 代码规范

- 遵循 `.ruff.toml`：`line-length = 100`，`target-version = "py312"`。
- 使用 `from __future__ import annotations` 保持前向兼容的类型注解。
- 所有公共函数和类必须带有类型注解和 docstring。

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

---

## 5. 与 instr-registry 的协作关系

| 仓库 | 内容 | AI 约束 |
|------|------|---------|
| `instr-core` | Python 核心库（MCP Server、验证引擎） | 不写 YAML，不改 `registry/` 数据 |
| `instr-registry` | 纯数据仓库（YAML 仪器描述） | 不写代码，只写 YAML |

> 两个仓库通过 GitHub Raw URL 耦合：`instr-core` 在运行时从 `instr-registry` 拉取 YAML。YAML 的编写规范详见 `instr-registry/CLAUDE.md`。
