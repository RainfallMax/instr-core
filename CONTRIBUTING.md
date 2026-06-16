# Contributing to instr-core

Thank you for your interest in making instrument control safer for AI-generated code!

## Local Development

We use [uv](https://docs.astral.sh/uv/) for Python environment and dependency management.

```bash
# Clone the repository
git clone <repo-url>
cd instr-core

# Sync dependencies and create virtual environment
uv sync

# Run the MCP server locally (uses the built-in registry)
uv run instr-core

# Run tests
uv run pytest tests/ -v

# Lint and format code before committing
uv run ruff check .
uv run ruff format .
```

## Desktop App Development

The desktop app requires **Node.js** (>= 20) and **Rust** (>= 1.75) in addition to Python.

### Prerequisites

```bash
# Install Node.js (if not already installed)
# https://nodejs.org/

# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install Tauri CLI
cargo install tauri-cli
```

### Development workflow

You need **two terminals** running simultaneously:

**Terminal 1 — Python backend:**
```bash
uv run python src/instr_core/api_server.py
# API will be available at http://localhost:8765
```

**Terminal 2 — Tauri frontend:**
```bash
cd desktop
npm install          # First time only
cargo tauri dev      # Starts the desktop window
```

The Tauri window will open automatically. The React UI communicates with the Python backend via HTTP on `localhost:8765`.

### Production build

```bash
cd desktop
cargo tauri build
# Output bundles are in src-tauri/target/release/bundle/
```

### Desktop file layout

```
desktop/
├── package.json              # Node.js dependencies
├── vite.config.ts            # Vite dev server config (port 1420)
├── tsconfig.json             # TypeScript strict mode
├── index.html
└── src/
    ├── main.tsx              # React entry point
    ├── App.tsx               # Main layout (instrument panels + SCPI terminal)
    ├── App.css               # Dark theme styles
    └── components/           # (future) Reusable UI components
└── src-tauri/
    ├── Cargo.toml            # Rust dependencies
    ├── tauri.conf.json       # Window config, security, bundle settings
    ├── build.rs              # Build script
    └── src/
        ├── main.rs           # Entry: spawns Python backend, manages lifecycle
        └── lib.rs            # Library entry (for testing)
```

### Adding a new API endpoint

1. **Python backend** (`src/instr_core/api_server.py`):
   - Add a Pydantic request/response model
   - Add a FastAPI route handler
   - Re-use `validator.py` for validation; do not bypass the safety layer

2. **React frontend** (`desktop/src/App.tsx` or new component):
   - Call the endpoint via `fetch(`${API_BASE}/your-endpoint`)`
   - Update state and render the response

3. **Test both sides** before committing.

## Adding a New Instrument Schema

Instrument schemas are maintained in a separate registry (see [`instr-registry`](https://github.com/instr-mcp/instr-registry)). To add a new instrument:

1. Clone the registry repository and create a directory for the manufacturer:
   ```text
   registry/
   ├── keithley/
   ├── keysight/
   ├── tektronix/          <-- new
   └── rohde-schwarz/
   ```

2. Add a `.yaml` file inside that directory. The filename should match the model or series name:
   ```text
   registry/tektronix/
   └── mso56.yaml
   ```

3. Follow the schema specification documented in [`AGENTS.md`](./AGENTS.md). At minimum, your YAML must include:
   - `instrument` — manufacturer, model, description
   - `global_limits` — absolute maximum voltage, current, and power
   - `commands` — allowed SCPI commands with ranges, `requires`, `forbidden_when`, and `safety` rules

4. Run the tests to ensure your YAML parses correctly:
   ```bash
   uv run pytest tests/test_schema.py -v
   ```

## Code Style

- We target **Python 3.12+**.
- All code must pass `ruff check .` and `ruff format .`.
- Type hints are encouraged for new functions.
- Frontend (TypeScript/React) uses strict mode as configured in `desktop/tsconfig.json`.

## Questions?

Open an issue or start a discussion. We're especially interested in:

- Real-world instrument schemas
- SCPI semantics and state-machine rules
- Safety constraints for high-power or sensitive devices
- Desktop UI improvements and instrument panel designs
