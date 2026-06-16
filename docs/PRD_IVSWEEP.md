# PRD: IV Sweep 数据采集与绘图

> 产品需求文档 | instr-core v0.3.0 | 2026-06-05

---

## 1. 功能概述

IV Sweep（电流-电压扫描）是半导体器件测试中最核心的测量模式。用户配置一个电压扫描范围，instr-core 自动步进改变源表（SMU）的输出电压，在每个电压点测量对应的电流值，最终绘制 I-V 特性曲线。

**核心价值**：将"写 Python 脚本 → 手动运行 → 用 matplotlib 画图"的繁琐流程，压缩为 Desktop UI 上的几次点击。

---

## 2. 目标用户

- 半导体器件测试工程师
- 材料科学实验室研究员
- 需要快速验证器件 I-V 特性的硬件工程师

---

## 3. 核心功能点

### 3.1 扫描参数配置

用户通过 UI 面板配置以下参数：

| 参数 | 类型 | 默认值 | 约束 |
|------|------|--------|------|
| Start Voltage (Vstart) | float | 0.0 | 必须在仪器 voltage global_limits 范围内 |
| Stop Voltage (Vstop) | float | 10.0 | 必须在仪器 voltage global_limits 范围内 |
| Step Size (Vstep) | float | 0.1 | > 0，且 (Vstop - Vstart) / Vstep 为合理整数（< 10,000 点） |
| Compliance Current (Icomp) | float | 0.01 | > 0，且必须在仪器 current global_limits 范围内 |
| Source Mode | enum | "VOLT" | 固定为 VOLT（电压源模式） |
| Delay (ms) | int | 10 | ≥ 0，每个步进后的稳定等待时间 |
| Sweep Direction | enum | "UP" | "UP" / "DOWN" / "BOTH" |

**约束验证**：
- 所有数值参数必须在对应仪器的 `global_limits` 范围内
- 如果 Vstart > Vstop，自动理解为反向扫描（或提示用户选择方向）
- 总点数 = |Vstop - Vstart| / Vstep + 1，超过 10,000 点时拒绝并提示

### 3.2 扫描执行流程

```
1. 验证所有参数通过 instrument schema
2. 发送安全初始化序列：
   *RST
   :OUTP OFF
   :SOUR:FUNC VOLT
   :SENS:CURR:PROT <Icomp>
   :SOUR:VOLT:RANG <max(|Vstart|, |Vstop|)>
   :SOUR:VOLT <Vstart>
3. 启用输出: :OUTP ON
4. FOR each voltage point in sweep:
      a. :SOUR:VOLT <Vpoint>
      b. 等待 delay ms
      c. :READ?  → 获取电流读数
      d. 记录 (Vpoint, Iread)
      e. 实时推送到前端 UI
5. 扫描结束: :OUTP OFF
6. 可选: 发送 *RST（用户可配置）
```

**关键安全行为**：
- 参数配置阶段：每个参数单独调用 `validate_command`，失败时阻止扫描启动
- 扫描执行阶段：如果某一步的 `validate_command` 失败（理论上不应发生，因为参数已验证），立即停止扫描并关闭输出
- 用户可随时点击"Stop"中断扫描，中断时立即发送 `:OUTP OFF`

### 3.3 实时数据展示

前端以两个视图同时展示数据：

**A. 实时数值表格**
- 两列：Voltage (V), Current (A)
- 新行追加到底部
- 显示当前行号 / 总行数
- 支持清空表格

**B. 实时 I-V 曲线图**
- X轴：Voltage (V)
- Y轴：Current (A)
- 每个新数据点到达时实时更新曲线
- 支持缩放、平移（基础版可不做交互缩放）
- 扫描方向为 "BOTH" 时，正向扫描和反向扫描用不同颜色区分

### 3.4 数据导出

扫描完成后，用户可将数据导出为 CSV：
- 文件名格式：`IV_{manufacturer}_{model}_{timestamp}.csv`
- 内容：
  ```csv
  Voltage(V),Current(A),Timestamp
  0.0,0.000001,2026-06-05T10:30:00.123Z
  0.1,0.000002,2026-06-05T10:30:00.456Z
  ...
  ```

### 3.5 扫描历史与回放

- 每次完成的扫描在内存中保存为一个 "SweepSession"
- 左侧面板显示历史扫描列表（时间、仪器、点数）
- 点击历史项可重新查看图表和数据
- 内存中保留最近 20 次扫描（超过时丢弃最旧的）

---

## 4. 边缘场景与异常处理

### 4.1 参数配置阶段

| 场景 | 预期行为 |
|------|---------|
| 用户输入的电压超出仪器范围 | 实时验证失败，输入框标红，显示 "Exceeds max voltage: 40V" |
| 步长为 0 或负数 | 实时验证失败，提示 "Step must be > 0" |
| 总点数 > 10,000 | 扫描按钮禁用，提示 "Too many points (14,230). Max: 10,000. Increase step size." |
| 仪器未连接 | 扫描按钮禁用，提示 "Connect an instrument first" |
| 仪器无匹配的 schema | 允许扫描但不验证参数范围，提示 "No schema — parameters not validated" |

### 4.2 扫描执行阶段

| 场景 | 预期行为 |
|------|---------|
| 用户在扫描中途点击 Stop | 立即发送 `:OUTP OFF`，标记扫描为 "ABORTED"，保留已采集的数据 |
| 仪器通信超时 | 标记扫描为 "ERROR"，显示错误信息，自动发送 `:OUTP OFF` |
| 某一步的读数返回 "+9.91E+37"（溢出/错误码） | 记录为 NaN，图表中该点不绘制，表格中显示 "OVERFLOW" |
| 扫描期间仪器断开连接 | 捕获异常，标记为 "ERROR"，`:OUTP OFF`，保留已采集数据 |
| 双向扫描时正向和反向点数不一致 | 允许，分别绘制两条曲线 |

### 4.3 数据展示阶段

| 场景 | 预期行为 |
|------|---------|
| 扫描数据点很多（> 1000） | 图表使用 SVG 或 Canvas 渲染，避免 DOM 节点爆炸 |
| 用户切换仪器 | 清空当前扫描数据和图表（但保留历史记录） |
| 浏览器刷新 | 丢失未导出的当前扫描数据（内存存储），历史记录也丢失（v0.3.x 不实现持久化） |

---

## 5. 交互逻辑

### 5.1 主界面布局（新增 IV Sweep 面板）

```
┌─────────────────────────────────────────────┐
│ instr-core · API ok · 2 schemas · pyvisa: T │
├─────────────────────────────────────────────┤
│ [Main] [Browse Schemas] [IV Sweep]          │  ← 新增 IV Sweep tab
├─────────────────────────────────────────────┤
│ IV Sweep View:                              │
│ ┌──────────────┬──────────────────────────┐ │
│ │ Configuration│  Real-time Chart          │ │
│ │              │  ┌────────────────────┐  │ │
│ │ Start: 0     │  │                    │  │ │
│ │ Stop:  20    │  │  I-V Curve         │  │ │
│ │ Step:  0.5   │  │  (live updating)   │  │ │
│ │ Comp:  0.01  │  │                    │  │ │
│ │ Delay: 10ms  │  └────────────────────┘  │ │
│ │ Dir:  UP     │                          │ │
│ │              │  ┌────────────────────┐  │ │
│ │ [Start Sweep]│  │ Data Table         │  │ │
│ │ [Stop]       │  │ V(V)    I(A)       │  │ │
│ │              │  │ 0.0     1.2e-6     │  │ │
│ │ ──────────── │  │ 0.5     1.5e-6     │  │ │
│ │ Sweep History│  │ ...                │  │ │
│ │ • 10:30 (240)│  └────────────────────┘  │ │
│ │ • 10:15 (120)│                          │ │
│ │              │  [Export CSV]            │ │
│ └──────────────┴──────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### 5.2 状态机

```
IDLE ──(Start clicked, params valid)──▶ RUNNING
  ↑                                        │
  │                                        │ (Stop clicked / error / complete)
  │                                        ▼
  └──────────────────────────────────── COMPLETED / ABORTED / ERROR
```

### 5.3 扫描过程中的UI反馈

- **IDLE**：Start 按钮可用，Stop 按钮禁用，配置面板可编辑
- **RUNNING**：Start 按钮禁用，Stop 按钮可用（红色），配置面板禁用，显示进度条或 "Scanning: 45/200 points"
- **COMPLETED**：Start 按钮恢复可用，Stop 按钮禁用，配置面板恢复可编辑，显示 "Completed: 200 points in 3.2s"
- **ABORTED**：同 COMPLETED，但显示 "Aborted at 45/200 points"
- **ERROR**：显示红色错误信息，Start 按钮可用

---

## 6. 安全考虑

- **参数预验证**：所有扫描参数在启动前必须通过 `validate_command`，任何失败阻止扫描
- **输出保护**：扫描结束后必须发送 `:OUTP OFF`，无论扫描是成功、中断还是报错
- **compliance 强制设置**：扫描启动前必须设置电流 compliance，否则阻止扫描
- **紧急停止**：Stop 按钮必须可靠，即使在通信异常时也要尝试发送 `:OUTP OFF`
- **双向扫描的电压安全**：正向扫描到 Vstop 后反向扫描回 Vstart，确保不会意外超压

---

## 7. 非功能需求

- **响应性**：UI 在扫描过程中保持响应，数据更新延迟 < 100ms
- **可扩展性**：架构应支持未来添加其他扫描类型（如 CV Sweep、脉冲扫描）
- **可测试性**：扫描逻辑应与 UI 解耦，可在无 UI 环境下单元测试
- **性能**：1000 点扫描应在 30 秒内完成（含 10ms delay）
