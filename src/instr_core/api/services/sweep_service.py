from __future__ import annotations

from ...schema import InstrumentSchema
from ...sweep import SweepConfig


def validate_sweep_config(config: SweepConfig, schema: InstrumentSchema) -> None:
    """Validate sweep configuration against instrument global limits.

    In ``CURR`` mode the sourced quantity is current and the compliance is a
    voltage limit, mirroring ``VOLT`` mode.
    """
    limits = schema.global_limits
    max_v = max(abs(config.start_voltage), abs(config.stop_voltage))

    if config.source_mode == "CURR":
        if limits.current is not None and max_v > limits.current.max:
            raise ValueError(
                f"Current exceeds max {limits.current.max} {limits.current.unit}"
            )
        if limits.voltage is not None and config.compliance > limits.voltage.max:
            raise ValueError(
                f"Compliance exceeds max {limits.voltage.max} {limits.voltage.unit}"
            )
    else:
        if limits.voltage is not None and max_v > limits.voltage.max:
            raise ValueError(
                f"Voltage exceeds max {limits.voltage.max} {limits.voltage.unit}"
            )
        if limits.current is not None and config.compliance > limits.current.max:
            raise ValueError(
                f"Compliance exceeds max {limits.current.max} {limits.current.unit}"
            )

    if config.step <= 0:
        raise ValueError("Step must be > 0")

    # Use round-trip via integer steps to avoid fp accumulation error.
    n_steps = int(round(abs(config.stop_voltage - config.start_voltage) / config.step))
    total = n_steps + 1
    if total > 10000:
        raise ValueError(f"Too many points: {total}. Max: 10,000")
