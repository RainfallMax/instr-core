# PRD: 自动仪器检测 UI 闭环

> 产品需求文档 | instr-core v0.3.1 | 2026-06-06

---

## 1. 功能概述

当用户通过 VISA 连接一台物理仪器时，系统已经通过 `*IDN?` 自动匹配到了对应的 schema（路径 A 的基础设施）。但当前 UI 只是把 schema_key 显示为一个蓝色小标签（如 "(keithley/smu/2600)"），用户需要手动切换到 "Browse Schemas" 视图，再找到对应的仪器，才能查看命令树。

本功能的目标：**连接仪器后，一键查看该仪器的完整 Schema Browser**。

---

## 2. 核心功能点

### 2.1 连接后自动提示

当 `/visa/connect` 返回的 `ConnectedInstrument` 包含 `schema_key` 时：

1. 在 "Connected" 面板中，仪器信息下方显示一个可点击的链接/按钮：
   ```
   Keithley 2602B
   USB0::0x05E6::0x2600::INSTR
   [Browse Schema]  ← 新增
   ```

2. 点击 "Browse Schema" 按钮：
   - 自动切换到 "Browse Schemas" 视图
   - 自动加载并显示该仪器的完整 schema（命令树 + 安全限制）
   - 不需要用户手动搜索或选择

### 2.2 Schema Browser 自动加载

SchemaBrowser 组件支持通过 `schemaKey` prop 自动加载。当 `schemaKey` 从 `undefined` 变为有效值时：
- 自动触发 `fetch(`${API_BASE}/instruments/${schemaKey}`)`
- 显示仪器信息、命令树、安全限制

### 2.3 主视图中的快捷入口

在 "Main" 视图的 Connected 面板中，每个已连接仪器增加一个操作区：

```
┌─────────────────────────────────┐
│ Connected                       │
│ ┌─────────────────────────────┐ │
│ │ ○ Keithley 2602B            │ │
│ │   USB0::0x05E6::0x2600::INSTR│ │
│ │   [keithley/smu/2600]       │ │
│ │   [Browse Schema] [Terminal]│ │ ← 新增操作按钮
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

- **Browse Schema**: 切换到 Schema 视图，自动加载该仪器的 schema
- **Terminal**: 将 SCPI Terminal 的选中仪器设为该仪器（自动选中）

### 2.4 无 Schema 时的降级

如果仪器连接后没有匹配的 schema（`schema_key` 为 `null`）：
- 显示提示："No schema matched. Instrument not recognized."
- "Browse Schema" 按钮禁用
- 可选：显示 "Suggest adding this instrument to registry" 链接（指向 GitHub issue 模板）

---

## 3. 交互流程

```
用户点击 VISA Resources 中的 "Connect"
    │
    ▼
/api_server.py: /visa/connect 返回 ConnectedInstrument(schema_key=...)
    │
    ▼
App.tsx: connected 数组新增仪器
    │
    ▼
ConnectedPanel: 显示仪器信息 + [Browse Schema] 按钮
    │
    ▼
用户点击 [Browse Schema]
    │
    ▼
App.tsx: setSelectedSchemaKey(schema_key) + setActiveView("schema")
    │
    ▼
SchemaBrowser: schemaKey prop 变化 → 自动加载 /instruments/{schemaKey}
    │
    ▼
显示：仪器信息 + Command Tree + Safety Limits
```

---

## 4. 边缘场景

| 场景 | 行为 |
|------|------|
| 连接多台仪器，每台都有 schema | Connected 面板每台都显示 [Browse Schema] |
| 连接多台仪器，其中一台无 schema | 有 schema 的显示按钮，无 schema 的显示提示 |
| 用户已在 Schema Browser 视图，又连接新仪器 | 点击新仪器的 [Browse Schema] 替换当前显示的 schema |
| 用户点击 [Browse Schema] 后返回 Main 视图 | 保持 selectedSchemaKey，再次点击可快速返回 |
| 仪器断开连接 | connected 数组移除该仪器，不影响 Schema Browser 的显示 |

---

## 5. 验收标准

- [ ] 连接有 schema 的仪器后，Connected 面板显示 [Browse Schema] 按钮
- [ ] 点击 [Browse Schema] 自动切换到 Schema 视图并加载对应 schema
- [ ] 无 schema 的仪器显示提示信息，按钮禁用
- [ ] 点击 [Terminal] 自动在 SCPI Terminal 中选中该仪器
- [ ] 所有现有功能不受影响
