"""Deterministic natural-language parser for the first agent workflows."""

from __future__ import annotations

import re

from .models import ParsedIvSweepIntent


class AgentParseError(ValueError):
    """Raised when a natural-language goal cannot be parsed safely."""


_NUMBER_UNIT = r"([-+]?\d+(?:\.\d+)?)\s*(mV|V|uA|µA|mA|A|ms|s)\b"


def _unit_value(number: str, unit: str) -> float:
    value = float(number)
    normalized = unit.lower().replace("µ", "u")
    if normalized == "v":
        return value
    if normalized == "mv":
        return value / 1000.0
    if normalized == "a":
        return value
    if normalized == "ma":
        return value / 1000.0
    if normalized == "ua":
        return value / 1_000_000.0
    if normalized == "s":
        return value * 1000.0
    if normalized == "ms":
        return value
    raise AgentParseError(f"Unsupported unit: {unit}")


def _extract_voltage_range(text: str) -> tuple[float | None, float | None]:
    match = re.search(
        rf"(?:sweep|scan|from)?\s*{_NUMBER_UNIT}\s*(?:to|->|through)\s*{_NUMBER_UNIT}",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None

    start_num, start_unit, stop_num, stop_unit = match.groups()
    if "a" in start_unit.lower() or "a" in stop_unit.lower():
        return None, None
    return _unit_value(start_num, start_unit), _unit_value(stop_num, stop_unit)


def _extract_step(text: str) -> float | None:
    match = re.search(
        rf"(?:step|steps|in)\s+{_NUMBER_UNIT}(?:\s*(?:step|steps))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    number, unit = match.groups()
    if "a" in unit.lower() or unit.lower() in ("ms", "s"):
        return None
    return _unit_value(number, unit)


def _extract_compliance(text: str) -> float | None:
    match = re.search(
        rf"(?:compliance|limit|current limit)\s*(?:of|at|=|:)?\s*{_NUMBER_UNIT}",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf"{_NUMBER_UNIT}\s*(?:compliance|current limit)",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    number, unit = match.groups()
    if "v" in unit.lower() or unit.lower() in ("ms", "s"):
        return None
    return _unit_value(number, unit)


def _extract_delay_ms(text: str) -> int:
    match = re.search(
        rf"(?:delay|settle|settling)\s*(?:of|=|:)?\s*{_NUMBER_UNIT}",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf"{_NUMBER_UNIT}\s*(?:delay|settle|settling)",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        return 10
    number, unit = match.groups()
    if unit.lower() not in ("ms", "s"):
        return 10
    return int(round(_unit_value(number, unit)))


def _extract_direction(text: str) -> str:
    lowered = text.lower()
    if "both" in lowered or "up and down" in lowered or "round trip" in lowered:
        return "BOTH"
    if "down" in lowered and "direction" in lowered:
        return "DOWN"
    return "UP"


def parse_iv_sweep_goal(goal: str) -> ParsedIvSweepIntent:
    """Parse a natural-language IV sweep goal into structured values."""
    start, stop = _extract_voltage_range(goal)
    step = _extract_step(goal)
    compliance = _extract_compliance(goal)

    missing: list[str] = []
    if start is None:
        missing.append("start voltage")
    if stop is None:
        missing.append("stop voltage")
    if step is None:
        missing.append("step")
    if compliance is None:
        missing.append("compliance")
    if missing:
        raise AgentParseError(
            "Could not safely parse required IV sweep field(s): " + ", ".join(missing)
        )

    assert start is not None
    assert stop is not None
    assert step is not None
    assert compliance is not None

    return ParsedIvSweepIntent(
        start_voltage=start,
        stop_voltage=stop,
        step=step,
        compliance=compliance,
        delay_ms=_extract_delay_ms(goal),
        direction=_extract_direction(goal),  # type: ignore[arg-type]
    )
