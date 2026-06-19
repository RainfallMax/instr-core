# PRD: 安全与正确性修复 (Security Fix Round 001)

> 产品需求文档 | instr-core v0.3.0-hotfix | 2026-06-05

---

## 1. 修复范围

本次修复针对代码审查中发现的 4 个高优先级安全与正确性问题：

| ID | 问题 | 严重性 | 文件 |
|----|------|--------|------|
| SF-001 | Sweep异常时 `:OUTP OFF` 失败被静默忽略 | 🔴 P0 | `sweep/engine.py` |
| SF-002 | `_address_to_schema` / `_address_state` 无锁保护 | 🔴 P0 | `api_server.py` |
| SF-003 | `VisaResourcePanel` 连接失败无错误处理 | 🔴 P0 | `VisaResourcePanel.tsx` |
| SF-004 | Sweep状态端点每次都返回全部数据点 | 🔴 P0 | `api_server.py` |

---

## 2. 详细需求

### SF-001: 异常时 `:OUTP OFF` 失败被静默忽略

#### 当前行为
`sweep/engine.py` 第 160-169 行：
```python
except Exception as exc:
    logger.exception("Sweep %s failed: %s", session.session_id, exc)
    try:
        visa.write(":OUTP OFF")
    except Exception:
        pass  # ← 静默忽略
```

如果仪器在扫描过程中出错（如过流保护触发、通信断开），`:OUTP OFF` 发送也可能失败。此时仪器输出可能保持开启状态，存在硬件损坏或人身伤害风险。

#### 期望行为
1. **记录**: 每次尝试 `:OUTP OFF` 的结果必须被记录（成功或失败）
2. **重试**: 第一次失败后，等待 100ms 重试一次
3. **降级**: 如果 `visa.write` 失败，尝试发送 `*RST` 作为紧急复位
4. **警报**: 如果所有尝试都失败，记录 CRITICAL 级别日志，包含 session_id 和仪器地址
5. **永不静默**: 禁止 `except Exception: pass` 模式

#### 验收标准
- [x] `visa.write(":OUTP OFF")` 失败后记录 WARNING
- [x] 第一次失败后等待 100ms 并重试 `:OUTP OFF`
- [x] 所有尝试都失败后记录 CRITICAL 级别的 "output may still be ON"
- [x] 关断路径不存在 `except Exception: pass` 或 `except: pass` 模式

#### 边缘场景
- 仪器在异常时已物理断开 → `visa.write` 抛出 `VisaIOError` → 记录为 WARNING（不可控）
- `*RST` 发送也失败 → 记录 CRITICAL，但不再继续尝试
- 线程被强制终止 → 无法执行 finally 块 → 此为操作系统级别问题，不在本修复范围内

---

### SF-002: `_address_to_schema` / `_address_state` 无锁保护

#### 当前行为
`api_server.py` 第 180-188 行：
```python
_address_to_schema: dict[str, str | None] = {}
_address_state: dict[str, dict[str, str]] = {}
```

这两个全局字典被多个 FastAPI worker 线程并发读写（`/visa/connect` 写入，`/visa/command` 和 `/validate/command` 读取），但没有锁保护。FastAPI 使用线程池处理并发请求，可能触发：
- `RuntimeError: dictionary changed size during iteration`
- 脏读（读取到半写入状态）
- 写入丢失

#### 期望行为
1. **加锁**: 所有读写操作通过 `threading.RLock` 保护
2. **快照**: 读取时返回字典的快照（浅拷贝），避免在持有锁期间迭代
3. **封装**: 提供内部辅助方法 `_get_address_schema()`, `_set_address_schema()`, `_get_address_state()`, `_update_address_state()`，禁止直接访问裸字典
4. **保持兼容**: 现有 API 行为不变，仅内部实现加锁

#### 验收标准
- [x] `_address_to_schema` 和 `_address_state` 的读写均有锁保护
- [x] API 路由通过封装助手访问地址状态
- [x] 并发场景不会迭代可变的地址状态字典
- [x] Python 全量测试通过

#### 边缘场景
- 大量并发 `/visa/command` 请求 → RLock 保证顺序执行，性能损失可接受（μs 级）
- `/visa/connect` 和 `/visa/command` 同时访问同一地址 → RLock 保证原子性

---

### SF-003: `VisaResourcePanel` 连接失败无错误处理

#### 当前行为
`VisaResourcePanel.tsx` 第 13-18 行：
```typescript
const connectInstrument = async (address: string) => {
    const res = await fetch(`${API_BASE}/visa/connect?address=${...}`, { method: "POST" });
    const data: ConnectedInstrument = await res.json();  // ← 不检查 res.ok
    onConnect(data);  // ← 可能传入错误响应
};
```

如果 `/visa/connect` 返回 500（如 PyVISA 未安装、仪器无响应），`res.json()` 会解析错误响应体（可能是 `{ detail: "..." }`），然后作为 `ConnectedInstrument` 传递给父组件。父组件会将其加入 `connected` 列表，用户点击后会导致后续操作失败。

#### 期望行为
1. **检查响应**: 连接前检查 `res.ok`，非 2xx 时抛出错误
2. **错误提示**: 显示用户友好的错误信息（如 "Connection failed: PyVISA not installed"）
3. **状态反馈**: 连接过程中显示 loading 状态，连接失败后恢复按钮
4. **不回退**: 连接失败时不调用 `onConnect`，不污染 connected 列表

#### 验收标准
- [x] `/visa/connect` 返回非 2xx 时，不调用 `onConnect`
- [x] 错误信息以红色文本显示在 VISA Resources 面板中
- [x] 错误信息在 5 秒后自动消失
- [x] 连接按钮在请求期间禁用

#### 边缘场景
- 网络断开 → fetch 抛出异常 → 显示 "Network error"
- 服务器 500 但返回非 JSON → `res.json()` 抛出 → 显示 "Server error"
- 用户快速点击多个 Connect 按钮 → loading 状态阻止重复请求

---

### SF-004: Sweep状态端点每次都返回全部数据点

#### 当前行为
`/sweep/{session_id}/status` 每次都返回 `session.points` 的全部内容：
```python
new_points = [p.model_dump() for p in session.points]
```

对于 10,000 点的扫描，每次轮询（200ms）传输 10,000 × 3 字段 = 30,000 个 JSON 值。总传输量 ≈ 10,000 × 50 轮询 × 200 字节 = **100 MB**。

#### 期望行为
1. **增量查询**: 支持可选参数 `?since_index=N`，只返回索引 >= N 的点
2. **默认值**: 无 `since_index` 时返回全部点（向后兼容）
3. **前端适配**: 前端轮询时传递上次接收到的点数作为 `since_index`
4. **性能**: 10,000 点扫描的总传输量降至 ~10,000 × 200 字节 = **2 MB**（降 50 倍）

#### 验收标准
- [x] `GET /sweep/{id}/status` 支持可选查询参数 `since_index`（整数，默认 0）
- [x] `since_index` 为负数时按 0 处理，超出范围时返回空增量
- [x] 前端轮询传递已接收点数作为 `since_index`
- [x] 不带 `since_index` 时返回全部点

#### 边缘场景
- 前端第一次请求（无 since_index）→ 返回全部点
- 扫描速度快于轮询 → since_index 可能等于总点数 → 返回空数组
- 扫描被中断 → since_index 可能大于实际点数 → 返回空数组

---

## 3. 非功能需求

- **向后兼容**: 所有 API 行为在默认参数下保持不变
- **最小变更**: 每处修复的代码变更不超过 50 行（含注释和空行）
- **无新依赖**: 不引入新的 Python/npm 包
- **测试**: 每处修复至少有一个对应的测试用例

---

## 4. 验收检查清单

- [x] SF-001: 异常路径关断全部失败时日志中有 CRITICAL 记录
- [x] SF-002: 地址状态访问由 `RLock` 保护
- [x] SF-003: `/visa/connect` 失败时前端显示错误且不添加假仪器
- [x] SF-004: `since_index` 只返回指定索引后的点
- [x] 所有现有 Python 测试通过
