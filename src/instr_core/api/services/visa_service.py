from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from ...validator import Registry
from ..dependencies import _get_address_schema, _update_address_state_entry

logger = logging.getLogger("instr_core.api")

_rm: Any | None = None  # pyvisa ResourceManager, imported lazily
_rm_source: Any | None = None


def import_pyvisa() -> Any:
    """Import PyVISA or return the compatibility object patched on api_server."""
    from ... import api_server

    if api_server.pyvisa is not None:
        return api_server.pyvisa

    import pyvisa  # type: ignore[import-not-found]

    return pyvisa


def get_visa() -> Any:
    """Lazy-import pyvisa so the API server can start without it installed."""
    global _rm, _rm_source
    try:
        pyvisa_module = import_pyvisa()
    except ImportError:
        raise RuntimeError(
            "pyvisa is not installed. Install it with: uv pip install pyvisa"
        )

    if _rm is None or _rm_source is not pyvisa_module:
        try:
            _rm = pyvisa_module.ResourceManager()
            _rm_source = pyvisa_module
            logger.info("PyVISA ResourceManager initialized")
        except ImportError:
            raise RuntimeError(
                "pyvisa is not installed. Install it with: uv pip install pyvisa"
            )
    return _rm


def split_command_argument(cmd: str) -> tuple[str, str | None]:
    """Split a raw SCPI command string into command and argument.

    Examples::

        >>> split_command_argument(":SOUR:VOLT 10")
        (":SOUR:VOLT", "10")
        >>> split_command_argument(":MEAS:VPP?")
        (":MEAS:VPP?", None)
    """
    cmd = cmd.strip()
    if " " in cmd:
        command_str, argument = cmd.split(" ", 1)
        return command_str.strip(), argument.strip()
    return cmd, None


def update_address_state(
    request: Request,
    address: str,
    command: str,
    argument: str | None,
    registry: Registry,
) -> None:
    """Update the virtual instrument state for an address after a command is sent.

    Looks up the schema for the address and applies any ``sets_state``
    declarations defined for the command.
    """
    schema_key = _get_address_schema(request, address)
    if schema_key is None or registry is None:
        return

    schema = registry.try_get_schema(schema_key)
    if schema is None:
        return

    cmd_def = next((c for c in schema.commands if c.command == command), None)
    if cmd_def is None:
        return

    for key, template in cmd_def.sets_state.items():
        if template == "$ARGUMENT":
            value = argument
        elif template == "$ARGUMENT_UPPER":
            value = argument.upper() if argument else None
        else:
            value = template
        if value is not None:
            _update_address_state_entry(request, address, key, value)
