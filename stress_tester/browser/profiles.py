from __future__ import annotations

from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "win-chrome": {
        "browser": "chromium",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "is_mobile": False,
        "has_touch": False,
    },
    "mac-safari": {
        "browser": "webkit",
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
        "is_mobile": False,
        "has_touch": False,
    },
    "mac-firefox": {
        "browser": "firefox",
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
        "is_mobile": False,
        "has_touch": False,
    },
    "linux-chrome": {
        "browser": "chromium",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "UTC",
        "is_mobile": False,
        "has_touch": False,
    },
    "pixel-7": {
        "browser": "chromium",
        "viewport": {"width": 412, "height": 915},
        "is_mobile": True,
        "has_touch": True,
        "device_scale_factor": 2.6,
        "locale": "en-US",
        "timezone_id": "America/New_York",
    },
    "iphone-15": {
        "browser": "webkit",
        "viewport": {"width": 393, "height": 852},
        "is_mobile": True,
        "has_touch": True,
        "device_scale_factor": 3,
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
    },
}


def get_profile(name: str) -> dict[str, Any]:
    if name not in PROFILES:
        return PROFILES["win-chrome"].copy()
    return PROFILES[name].copy()
