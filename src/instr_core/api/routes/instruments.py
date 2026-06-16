from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_registry
from ..models import InstrumentMeta, InstrumentDetail, SafetyLimitsResponse

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentMeta])
def list_instruments(registry = Depends(get_registry)) -> list[InstrumentMeta]:
    keys = registry.list_instruments()
    results: list[InstrumentMeta] = []
    for key in keys:
        meta = registry.get_metadata(key)
        if meta:
            results.append(
                InstrumentMeta(
                    key=key,
                    manufacturer=meta.get("manufacturer", ""),
                    model=meta.get("model", ""),
                    description=meta.get("description"),
                )
            )
        else:
            results.append(InstrumentMeta(key=key, manufacturer="", model=""))
    return results


@router.get("/{instrument_key:path}/safety-limits", response_model=SafetyLimitsResponse)
def get_safety_limits(instrument_key: str, registry = Depends(get_registry)) -> SafetyLimitsResponse:
    try:
        schema = registry.get_schema(instrument_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Instrument '{instrument_key}' not found")
    limits = schema.global_limits
    return SafetyLimitsResponse(
        instrument=instrument_key,
        voltage=limits.voltage.model_dump() if limits.voltage else None,
        current=limits.current.model_dump() if limits.current else None,
        power=limits.power.model_dump() if limits.power else None,
        frequency=limits.frequency.model_dump() if limits.frequency else None,
    )


@router.get("/{instrument_key:path}/commands")
def get_command_tree(instrument_key: str, registry = Depends(get_registry)) -> list[dict[str, Any]]:
    try:
        schema = registry.get_schema(instrument_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Instrument '{instrument_key}' not found")
    return [cmd.model_dump(by_alias=True, exclude_none=True) for cmd in schema.commands]


@router.get("/{instrument_key:path}", response_model=InstrumentDetail)
def get_instrument(instrument_key: str, registry = Depends(get_registry)) -> InstrumentDetail:
    try:
        schema = registry.get_schema(instrument_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Instrument '{instrument_key}' not found")
    return InstrumentDetail(
        key=instrument_key,
        schema=schema.model_dump(by_alias=True, exclude_none=True),
    )
