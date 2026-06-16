# Architecture: 自动仪器检测 UI 闭环

> 架构设计文档 | instr-core v0.3.1 | 基于 PRD_AUTO_INSTRUMENT_DETECTION.md

---

## 1. 技术栈（无变化）

- 前端：React 18, TypeScript, CSS
- 后端：FastAPI（无变更）

---

## 2. 模块设计

### 2.1 数据流

```
用户点击 Connect
    │
    ▼
VisaResourcePanel.connectInstrument()
    │
    ▼
POST /visa/connect → 返回 ConnectedInstrument{..., schema_key}
    │
    ▼
App.tsx handleConnect(inst) → setConnected([...prev, inst])
    │
    ▼
ConnectedPanel 渲染 instrument card
    │
    ▼
用户点击 [Browse Schema]
    │
    ▼
ConnectedPanel.onBrowseSchema(schema_key) → App.handleBrowseSchema(schema_key)
    │
    ▼
App.tsx: setSelectedSchemaKey(schema_key) + setActiveView("schema")
    │
    ▼
SchemaBrowser schemaKey prop 变化 → useEffect 触发 fetch
    │
    ▼
GET /instruments/{schemaKey} → 显示 schema
```

### 2.2 组件变更

#### ConnectedPanel.tsx（修改）

新增 props：
```typescript
interface ConnectedPanelProps {
  connected: ConnectedInstrument[];
  selected: string;
  onSelect: (address: string) => void;
  onBrowseSchema?: (schemaKey: string) => void;  // 新增
  onOpenTerminal?: (address: string) => void;     // 新增
}
```

渲染变更：
```tsx
{inst.schema_key ? (
  <div className="instrument-actions">
    <button
      className="action-btn browse"
      onClick={() => onBrowseSchema?.(inst.schema_key!)}
    >
      Browse Schema
    </button>
    <button
      className="action-btn terminal"
      onClick={() => onOpenTerminal?.(inst.address)}
    >
      Terminal
    </button>
  </div>
) : (
  <span className="no-schema-hint">No schema matched</span>
)}
```

#### App.tsx（修改）

新增 handler：
```typescript
const handleBrowseSchema = (schemaKey: string) => {
  setSelectedSchemaKey(schemaKey);
  setActiveView("schema");
};

const handleOpenTerminal = (address: string) => {
  setSelectedInstrument(address);
  setActiveView("main");
};
```

ConnectedPanel 调用：
```tsx
<ConnectedPanel
  connected={connected}
  selected={selectedInstrument}
  onSelect={setSelectedInstrument}
  onBrowseSchema={handleBrowseSchema}
  onOpenTerminal={handleOpenTerminal}
/>
```

#### App.css（修改）

新增样式：
```css
.instrument-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.action-btn {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid;
}

.action-btn.browse {
  background: rgba(137, 180, 250, 0.15);
  border-color: rgba(137, 180, 250, 0.3);
  color: #89b4fa;
}

.action-btn.terminal {
  background: rgba(166, 227, 161, 0.15);
  border-color: rgba(166, 227, 161, 0.3);
  color: #a6e3a1;
}

.no-schema-hint {
  font-size: 0.75rem;
  color: #6c7086;
  font-style: italic;
  margin-top: 0.25rem;
}
```

---

## 3. 文件变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `desktop/src/components/ConnectedPanel.tsx` | 修改 | 新增 action 按钮 |
| `desktop/src/App.tsx` | 修改 | 新增 handler |
| `desktop/src/App.css` | 修改 | 新增样式 |
| `desktop/src/types.ts` | 修改 | ConnectedPanelProps 扩展 |

---

## 4. 风险评估

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| onBrowseSchema 回调未传递 | 低 | 中 | TypeScript 类型检查确保 |
| SchemaBrowser 加载失败 | 低 | 低 | 现有错误处理已覆盖 |
| 多仪器时 UI 拥挤 | 中 | 低 | 按钮小尺寸，actions 区域紧凑 |
