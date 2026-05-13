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

## Questions?

Open an issue or start a discussion. We’re especially interested in:

- Real-world instrument schemas
- SCPI semantics and state-machine rules
- Safety constraints for high-power or sensitive devices
