from __future__ import annotations

from ...schema import InstrumentSchema
from ...sweep import SweepConfig


def validate_sweep_config(config: SweepConfig, schema: InstrumentSchema) -> None:
    """Validate sweep configuration against instrument global limits."""
    limits = schema.global_limits

    if limits.voltage is not None:
        max_v = limits.voltage.max
        if abs(config.start_voltage) > max_v or abs(config.stop_voltage) > max_v:
            raise ValueError(
                f"Voltage exceeds max {max_v} {limits.voltage.unit}"
            )

    if limits.current is not None:
        max_c = limits.current.max
        if config.compliance > max_c:
            raise ValueError(
                f"Compliance exceeds max {max_c} {limits.current.unit}"
            )

    if config.step <= 0:
        raise ValueError("Step must be > 0")

    # Use round-trip via integer steps to avoid fp accumulation error.
    n_steps = int(round(abs(config.stop_voltage - config.start_voltage) / config.step))
    total = n_steps + 1
    if total > 10000:
        raise ValueError(f"Too many points: {total}. Max: 10,000")
