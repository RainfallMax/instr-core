"""Pure preflight validation for hardware commands."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ...validator import Registry, validate_command
from ..dependencies import _get_address_schema, _get_address_state
from .visa_service import split_command_argument

DISCOVERY_QUERY_ALLOWLIST = frozenset({"*IDN?"})


@dataclass(frozen=True)
class CommandPreflight:
    """Approved command metadata produced before any hardware access."""

    command: str
    argument: str | None
    is_query: bool
    validated: bool
    issues: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()


class CommandRejected(ValueError):
    """A hardware command that cannot safely pass preflight."""

    def __init__(
        self,
        message: str,
        issues: list[str],
        suggestions: list[str],
    ) -> None:
        super().__init__(message)
        self.issues = issues
        self.suggestions = suggestions


def preflight_hardware_command(
    request: Request,
    address: str,
    raw_command: str,
    should_validate: bool,
    registry: Registry | None,
) -> CommandPreflight:
    """Validate a hardware command without opening a VISA resource."""
    command, argument = split_command_argument(raw_command)
    is_query = command.endswith("?")

    if not should_validate:
        raise CommandRejected(
            "Hardware command validation cannot be disabled",
            ["Validation bypass is not permitted"],
            ["Submit the command with validate=true"],
        )

    if is_query and command.upper() in DISCOVERY_QUERY_ALLOWLIST:
        return CommandPreflight(command, argument, True, False)

    schema_key = _get_address_schema(request, address)
    if schema_key is None:
        raise CommandRejected(
            "No schema available for hardware command",
            ["The connected address has no matched instrument schema"],
            ["Connect a recognized instrument before sending this command"],
        )
    if registry is None:
        raise CommandRejected(
            "Instrument registry is unavailable",
            ["The hardware command cannot be validated"],
            ["Configure the registry and retry"],
        )

    schema = registry.try_get_schema(schema_key)
    if schema is None:
        raise CommandRejected(
            f"Instrument schema '{schema_key}' is unavailable",
            ["The mapped schema could not be loaded"],
            ["Refresh the registry or reconnect the instrument"],
        )

    state = _get_address_state(request, address) or {}
    result = validate_command(schema, command, argument, state)
    if not result.valid:
        raise CommandRejected(
            "Hardware command failed validation",
            result.issues,
            result.suggestions,
        )

    return CommandPreflight(
        command=command,
        argument=argument,
        is_query=is_query,
        validated=True,
        issues=tuple(result.issues),
        suggestions=tuple(result.suggestions),
    )
