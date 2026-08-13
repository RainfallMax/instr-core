#!/usr/bin/env python3
"""Export instr.web contracts, sync them into instr-core, and run compatibility tests."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_ROOT = PROJECT_ROOT.parent / "instr.web"
CORE_FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "web_contracts"
WEB_REGISTRY_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "web_registry"


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, env={**os.environ, "CI": "true"})


def require_node_24(web_root: Path) -> None:
    node_path = shutil.which("node")

    if node_path is None:
        raise RuntimeError(
            "Node.js is required to export instr.web contracts, but `node` was not found on PATH."
        )

    result = subprocess.run(
        [node_path, "--version"],
        cwd=web_root,
        check=True,
        capture_output=True,
        env={**os.environ, "CI": "true"},
        text=True,
    )
    version = result.stdout.strip()
    major = version.removeprefix("v").split(".", maxsplit=1)[0]

    if major != "24":
        raise RuntimeError(
            "instr.web requires Node.js 24.x to export contracts. "
            f"Found {version} at {node_path}. Put Node 24 first on PATH and rerun."
        )


def sync_fixtures(web_root: Path) -> list[Path]:
    exported_root = web_root / "tmp" / "core-schema-fixtures"
    exported_paths = sorted(exported_root.glob("*.json"))

    if not exported_paths:
        raise RuntimeError(
            f"No exported web contracts found in {exported_root}. "
            "Check that `pnpm schema:fixtures` completed successfully."
        )

    CORE_FIXTURES_ROOT.mkdir(parents=True, exist_ok=True)

    for old_path in CORE_FIXTURES_ROOT.glob("*.json"):
        old_path.unlink()

    synced_paths: list[Path] = []
    for source_path in exported_paths:
        target_path = CORE_FIXTURES_ROOT / source_path.name
        shutil.copyfile(source_path, target_path)
        synced_paths.append(target_path)

    return synced_paths


def sync_registry(web_root: Path) -> list[Path]:
    """Sync web-exported YAML registry files into the runtime registry fixtures."""
    exported_root = web_root / "tmp" / "registry"
    exported_paths = sorted(exported_root.rglob("*.yaml"))

    if not exported_paths:
        raise RuntimeError(
            f"No exported web registry found in {exported_root}. "
            "Check that `pnpm registry:export` completed successfully."
        )

    if WEB_REGISTRY_ROOT.exists():
        shutil.rmtree(WEB_REGISTRY_ROOT)
    WEB_REGISTRY_ROOT.mkdir(parents=True, exist_ok=True)

    synced_paths: list[Path] = []
    for source_path in exported_paths:
        rel = source_path.relative_to(exported_root)
        target_path = WEB_REGISTRY_ROOT / rel
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        synced_paths.append(target_path)

    return synced_paths


def python_for_pytest() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"

    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the cross-repo contract gate: export instr.web core schemas, "
            "sync them into instr-core fixtures, and execute pytest."
        )
    )
    parser.add_argument(
        "--web-root",
        type=Path,
        default=DEFAULT_WEB_ROOT,
        help="Path to the instr.web repository. Defaults to the sibling checkout.",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Only export and sync fixtures; do not run pytest.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    web_root = args.web_root.resolve()

    if not (web_root / "package.json").exists():
        raise RuntimeError(f"Could not find instr.web package.json at {web_root}")

    require_node_24(web_root)
    run(["corepack", "pnpm", "schema:fixtures"], cwd=web_root)
    synced_paths = sync_fixtures(web_root)

    print("Synced web contract fixtures:")
    for path in synced_paths:
        print(f"  {path.relative_to(PROJECT_ROOT)}")

    run(["corepack", "pnpm", "registry:export"], cwd=web_root)
    synced_registry = sync_registry(web_root)

    print("Synced web registry fixtures:")
    for path in synced_registry:
        print(f"  {path.relative_to(PROJECT_ROOT)}")

    if not args.skip_pytest:
        run(
            [python_for_pytest(), "-m", "pytest", "tests/test_web_contracts.py", "tests/test_web_registry.py", "-v"],
            cwd=PROJECT_ROOT,
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
