# Desktop App Development

This document covers the Tauri desktop application in detail.

## Quick Start

```bash
# 1. Start Python backend
uv run python src/instr_core/api_server.py

# 2. In another terminal, start Tauri dev
cd desktop
npm install
cargo tauri dev
```

## Architecture

```
Tauri (Rust)          HTTP         Python (FastAPI)
┌─────────────┐      ┌────┐       ┌─────────────┐
│ React UI    │◄────►│8765│◄─────►│ api_server  │
│ (WebView)   │      └────┘       │             │
└─────────────┘                   │  Registry   │
│  Window     │                   │  Validator  │
│  Menu       │                   │  PyVISA     │
│  Dialogs    │                   └─────────────┘
└─────────────┘
```

## Communication

### Frontend → Backend

```typescript
const API_BASE = "http://localhost:8765";

// GET request
const instruments = await fetch(`${API_BASE}/instruments`).then(r => r.json());

// POST request
const result = await fetch(`${API_BASE}/visa/command`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    address: "USB0::0x05E6::0x2600::INSTR",
    command: ":SOUR:VOLT 10",
    validate: true,
  }),
}).then(r => r.json());
```

### Backend → Frontend

The backend returns JSON responses:

```json
{
  "address": "USB0::0x05E6::0x2600::INSTR",
  "command": ":SOUR:VOLT 10",
  "response": null,
  "validated": true,
  "validation_issues": [],
  "validation_suggestions": []
}
```

## Development Workflow

### Adding a new API endpoint

1. Add model in `api_server.py`:
```python
class MyRequest(BaseModel):
    param: str

class MyResponse(BaseModel):
    result: str
```

2. Add route:
```python
@app.post("/my/endpoint", response_model=MyResponse)
def my_endpoint(req: MyRequest) -> MyResponse:
    return MyResponse(result=f"Hello {req.param}")
```

3. Call from React:
```typescript
const data = await fetch(`${API_BASE}/my/endpoint`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ param: "world" }),
}).then(r => r.json());
```

### Styling

The app uses a custom dark theme. Key CSS variables:

```css
--bg-primary: #0f0f1a;
--bg-panel: #181825;
--bg-item: #1e1e2e;
--border: #313244;
--text-primary: #cdd6f4;
--text-secondary: #a6adc8;
--accent-blue: #89b4fa;
--accent-green: #a6e3a1;
--accent-yellow: #f9e2af;
--accent-red: #f38ba8;
```

## Building

### Development

```bash
cd desktop
cargo tauri dev
```

### Production

```bash
cd desktop
cargo tauri build
```

Output:
- macOS: `src-tauri/target/release/bundle/dmg/*.dmg`
- Windows: `src-tauri/target/release/bundle/msi/*.msi`
- Linux: `src-tauri/target/release/bundle/deb/*.deb`

## Troubleshooting

### Python backend not found

Tauri tries to find `api_server.py` in this order:
1. Development: `../../src/instr_core/api_server.py`
2. Production: Resources directory

Make sure you're running from the project root.

### CORS errors

If you see CORS errors in the browser console, check:
1. `api_server.py` CORS config allows `localhost:1420`
2. Python backend is running on port 8765

### Port conflicts

Default ports:
- 8765: Python backend
- 1420: Vite dev server (Tauri frontend)

Change via environment variables:
```bash
INSTR_CORE_API_PORT=8888 uv run python src/instr_core/api_server.py
```
