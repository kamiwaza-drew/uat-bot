from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import Page


class ScreenshotManager:
    def __init__(self, run_dir: Path, quality_setting: str = "png") -> None:
        self.run_dir = run_dir
        self.quality_setting = quality_setting

    async def capture(
        self,
        page: Page,
        worker_id: str,
        step: int,
        action: str,
        *,
        full_page: bool = True,
    ) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        screenshots_dir = self.run_dir / "screenshots" / worker_id
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        image_type = "png"
        kwargs: dict[str, object] = {"full_page": full_page}
        if self.quality_setting.lower() != "png":
            image_type = "jpeg"
            kwargs["quality"] = max(0, min(100, int(self.quality_setting)))

        filename = f"{step:04d}_{action}_{timestamp}.{ 'png' if image_type == 'png' else 'jpg'}"
        path = screenshots_dir / filename
        await page.screenshot(path=str(path), type=image_type, **kwargs)
        return path
