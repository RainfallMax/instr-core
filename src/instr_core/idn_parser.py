"""Parser for standard SCPI *IDN? response strings."""

from __future__ import annotations

import re

from pydantic import BaseModel


class IDNInfo(BaseModel):
    """Parsed SCPI *IDN? response.

    Attributes:
        manufacturer: Normalized manufacturer name (lowercase, suffixes stripped).
        model: Normalized model identifier (e.g. "2602B", "DSOX1204G").
        serial: Serial number string, or None if absent.
        firmware: Firmware version string, or None if absent.
    """

    manufacturer: str
    model: str
    serial: str | None = None
    firmware: str | None = None


def _clean_manufacturer(mfr: str) -> str:
    """Normalize manufacturer string for matching.

    Steps:
        1. Lowercase.
        2. Strip common suffixes such as "INSTRUMENTS INC.", "TECHNOLOGIES",
           "INSTRUMENTS", "INC.", "CORP.", "CORPORATION".
    """
    mfr = mfr.lower().strip()
    # Ordered from longest to shortest so partial overlaps are handled first.
    suffixes = [
        "instruments inc.",
        "instruments",
        "technologies",
        "corporation",
        "corp.",
        "corp",
        "inc.",
        "inc",
    ]
    for suffix in suffixes:
        if mfr.endswith(f" {suffix}"):
            mfr = mfr[: -len(suffix) - 1]
    return mfr.strip()


def _clean_model(model: str) -> str:
    """Normalize model string for matching.

    Strips leading "MODEL " or "MODEL:" prefixes and surrounding whitespace.
    """
    model = model.strip()
    prefix_match = re.match(r"^(model)[:\s\-]*(.+)$", model, re.IGNORECASE)
    if prefix_match:
        return prefix_match.group(2).strip()
    return model


def parse_idn(idn: str) -> IDNInfo:
    """Parse a SCPI *IDN? response string.

    The standard format is::

        Manufacturer,Model,Serial,Firmware

    Examples::

        >>> parse_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1398987,3.2.0")
        IDNInfo(manufacturer="keithley", model="2602B", serial="1398987", firmware="3.2.0")
        >>> parse_idn("Keysight Technologies,DSOX1204G,CN12345678,02.42.2020012900")
        IDNInfo(manufacturer="keysight", model="DSOX1204G", serial="CN12345678", firmware="02.42.2020012900")
        >>> parse_idn("TEKTRONIX,MSO56,B010001,CF:91.1CT FV:1.0.0")
        IDNInfo(manufacturer="tektronix", model="MSO56", serial="B010001", firmware="CF:91.1CT FV:1.0.0")

    Args:
        idn: Raw *IDN? response string.

    Returns:
        An :class:`IDNInfo` instance with normalized fields.
    """
    parts = [p.strip() for p in idn.split(",")]
    manufacturer = _clean_manufacturer(parts[0]) if len(parts) > 0 else ""
    model = _clean_model(parts[1]) if len(parts) > 1 else ""
    serial = parts[2] if len(parts) > 2 else None
    firmware = parts[3] if len(parts) > 3 else None
    return IDNInfo(
        manufacturer=manufacturer,
        model=model,
        serial=serial,
        firmware=firmware,
    )
