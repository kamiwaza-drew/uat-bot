from __future__ import annotations

import pytest

from uat_bot.models import RunCreateRequest


def test_run_create_request_distribution_must_match_concurrency():
    with pytest.raises(ValueError):
        RunCreateRequest(
            concurrent_users=3,
            role_distribution={"admin": 1, "viewer": 1},
            browser_distribution={"chromium": 2, "firefox": 1},
            os_emulation=["win-chrome"],
            scenarios=["login"],
            duration_seconds=60,
            ramp_up_seconds=0,
            vision_enabled=False,
        )


def test_run_create_request_valid_payload():
    payload = RunCreateRequest(
        concurrent_users=3,
        role_distribution={"admin": 1, "viewer": 2},
        browser_distribution={"chromium": 2, "firefox": 1},
        os_emulation=["win-chrome", "mac-firefox"],
        scenarios=["login"],
        duration_seconds=120,
        ramp_up_seconds=10,
        vision_enabled=False,
    )
    assert payload.concurrent_users == 3
    assert payload.role_distribution["viewer"] == 2
