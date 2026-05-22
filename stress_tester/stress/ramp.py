from __future__ import annotations


def ramp_delay_seconds(index: int, total: int, ramp_up_seconds: int) -> float:
    if total <= 1 or ramp_up_seconds <= 0:
        return 0.0
    return (ramp_up_seconds / max(1, total - 1)) * index
