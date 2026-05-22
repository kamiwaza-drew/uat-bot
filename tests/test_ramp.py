from __future__ import annotations

from stress_tester.stress.ramp import ramp_delay_seconds


def test_ramp_delay_seconds():
    assert ramp_delay_seconds(index=0, total=5, ramp_up_seconds=40) == 0
    assert ramp_delay_seconds(index=4, total=5, ramp_up_seconds=40) == 40
    assert ramp_delay_seconds(index=2, total=1, ramp_up_seconds=40) == 0
