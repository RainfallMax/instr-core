"""Entry point for instr-core MCP server."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from . import __version__
from .registry_client import RegistryClient
from .server import create_server
from .validator import Registry


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Exposed as a module-level helper so tests can exercise argument
    parsing without invoking the server. ``main()`` calls it and then
    drives the rest of the startup sequence with the parsed args.
    """
    parser = argparse.ArgumentParser(prog="instr-core", description="instr-core MCP server")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print the instr-core version and exit.",
    )
    parser.add_argument(
        "--registry",
        action="append",
        default=[],
        help="Path to an instrument registry directory (can be used multiple times).",
    )
    parser.add_argument(
        "--registry-url",
        default=os.environ.get("INSTR_REGISTRY_URL"),
        help=("Base URL of the remote instr-registry (defaults to INSTR_REGISTRY_URL env var)."),
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("INSTR_CORE_LOG_LEVEL", "INFO").upper(),
        choices=_LOG_LEVELS,
        type=str.upper,
        metavar="LEVEL",
        help=(
            "Logging level (default: INFO). Also reads INSTR_CORE_LOG_LEVEL "
            f"from the environment. Choices: {', '.join(_LOG_LEVELS)}."
        ),
    )
    return parser


def _install_signal_handlers() -> None:
    """Install minimal SIGINT/SIGTERM handlers that log and exit cleanly.

    On Windows ``SIGTERM`` exists as a constant but the OS never sends it
    to a Python process; ``signal.signal`` still accepts it, so we
    register both unconditionally and let the platform decide what fires.
    """

    def _shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
        name = signal.Signals(signum).name
        logging.info("Received %s, shutting down instr-core.", name)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    paths = args.registry
    if not paths:
        env_path = os.environ.get("INSTR_CORE_REGISTRY")
        if env_path:
            # Allow comma-separated or path-separated lists
            normalized = env_path.replace(",", os.pathsep)
            paths = [p.strip() for p in normalized.split(os.pathsep) if p.strip()]

    try:
        if paths:
            registry = Registry.load(*paths)
        else:
            client = (
                RegistryClient(base_url=args.registry_url) if args.registry_url else RegistryClient()
            )
            registry = Registry.from_client(client)
    except (RuntimeError, FileNotFoundError) as exc:
        logging.error("Failed to initialize registry: %s", exc)
        sys.exit(1)

    logging.info("Starting instr-core MCP server, registry: %s", registry)
    logging.info("Indexed %d instrument(s)", len(registry))

    if len(registry) == 0:
        logging.warning(
            "Registry cache is empty; every tool call will need to fetch a schema "
            "from the remote registry. Verify network connectivity, or pre-populate "
            "the cache by running instr-core once while online."
        )

    _install_signal_handlers()

    mcp = create_server(registry)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
