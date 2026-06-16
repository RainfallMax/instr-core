#!/usr/bin/env python3
"""Development helper: start the Python API server for the Tauri desktop app."""

import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
api_script = project_root / "src" / "instr_core" / "api_server.py"

subprocess.run(
    [sys.executable, str(api_script)],
    cwd=project_root,
    env={**dict(subprocess.os.environ), "INSTR_CORE_API_PORT": "8765"},
)
