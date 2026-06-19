"""Shared emergency teardown for hardware output devices."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("instr_core.safety")


@dataclass(frozen=True)
class TeardownReport:
    """Result of a best-effort output shutdown sequence."""

    safe: bool
    attempted_commands: tuple[str, ...]
    successful_command: str | None
    errors: tuple[str, ...]


def safe_turn_off_output(
    visa: Any,
    operation_id: str,
    address: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TeardownReport:
    """Turn output off with one retry and a reset fallback."""
    attempted: list[str] = []
    errors: list[str] = []
    attempts = (
        (":OUTP OFF", ":OUTP OFF"),
        (":OUTP OFF", ":OUTP OFF retry"),
        ("*RST", "*RST fallback"),
    )

    for index, (command, label) in enumerate(attempts):
        attempted.append(command)
        try:
            visa.write(command)
            logger.info("%s: %s succeeded", operation_id, label)
            return TeardownReport(
                safe=True,
                attempted_commands=tuple(attempted),
                successful_command=command,
                errors=tuple(errors),
            )
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logger.warning("%s: %s failed: %s", operation_id, label, exc)
            if index == 0:
                sleep(0.1)

    logger.critical(
        "%s: CRITICAL: output may still be ON for %s",
        operation_id,
        address or "unknown address",
    )
    return TeardownReport(
        safe=False,
        attempted_commands=tuple(attempted),
        successful_command=None,
        errors=tuple(errors),
    )
