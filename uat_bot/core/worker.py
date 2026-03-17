from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Awaitable, Callable

from playwright.async_api import Browser, BrowserContext, Error, Page, async_playwright

from uat_bot.browser.profiles import get_profile
from uat_bot.browser.screenshots import ScreenshotManager
from uat_bot.config import Settings
from uat_bot.models import WorkerAssignment

MetricSink = Callable[[dict[str, Any]], Awaitable[None]]
EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class Worker:
    def __init__(
        self,
        run_id: str,
        assignment: WorkerAssignment,
        settings: Settings,
        screenshot_manager: ScreenshotManager,
        metric_sink: MetricSink,
        event_sink: EventSink,
        component: str | None = None,
        guidance_context: str | None = None,
        target_url: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.assignment = assignment
        self.settings = settings
        self.screenshot_manager = screenshot_manager
        self.metric_sink = metric_sink
        self.event_sink = event_sink
        self.component = component
        self.guidance_context = guidance_context or ""
        self.target_url = (target_url or settings.kamiwaza_url or "").rstrip("/")
        self._step = 0
        self.effective_browser = assignment.browser

    async def run(self, duration_seconds: int, cancel_event: asyncio.Event) -> None:
        started = perf_counter()
        profile = get_profile(self.assignment.os_profile)

        async with async_playwright() as pw:
            browser = await self._launch_browser(pw, self.assignment.browser)
            context = await browser.new_context(
                viewport=profile.get("viewport"),
                locale=profile.get("locale"),
                timezone_id=profile.get("timezone_id"),
                is_mobile=profile.get("is_mobile", False),
                has_touch=profile.get("has_touch", False),
                device_scale_factor=profile.get("device_scale_factor", 1),
                ignore_https_errors=True,
                record_har_path=None,
            )
            try:
                page = await context.new_page()
                await self._attach_listeners(page)
                await self._login(page)

                while perf_counter() - started < duration_seconds and not cancel_event.is_set():
                    self._step += 1
                    ts_start = perf_counter()
                    shot_path = await self.screenshot_manager.capture(
                        page,
                        self.assignment.worker_id,
                        self._step,
                        "heartbeat",
                        full_page=False,
                    )
                    duration_ms = int((perf_counter() - ts_start) * 1000)
                    await self.metric_sink(
                        {
                            "ts": datetime.now(UTC).isoformat(),
                            "run_id": self.run_id,
                            "worker_id": self.assignment.worker_id,
                            "user_id": self.assignment.user.username,
                            "role": self.assignment.user.role,
                            "browser": self.effective_browser,
                            "os_profile": self.assignment.os_profile,
                            "action": "heartbeat",
                            "status": "ok",
                            "duration_ms": duration_ms,
                            "screenshot": shot_path.name,
                            "detail": "post-login steady-state capture",
                        }
                    )
                    await self.event_sink(
                        "worker.screenshot",
                        {
                            "worker_id": self.assignment.worker_id,
                            "screenshot": shot_path.relative_to(self.screenshot_manager.run_dir).as_posix(),
                        },
                    )
                    await asyncio.sleep(5)
            finally:
                await context.close()
                await browser.close()

    @staticmethod
    def _chromium_executable() -> str | None:
        for candidate in ("chromium-browser", "chromium", "google-chrome"):
            path = shutil.which(candidate)
            if path:
                return path
        return None

    async def _launch_chromium(self, pw: Any) -> Browser:
        chrome_path = self._chromium_executable()
        if chrome_path:
            self.effective_browser = "chromium"
            return await pw.chromium.launch(
                executable_path=chrome_path,
                headless=True,
                args=["--no-sandbox"],
            )
        self.effective_browser = "chromium"
        return await pw.chromium.launch(headless=True)

    async def _emit_browser_fallback(self, requested: str, reason: str) -> None:
        await self.metric_sink(
            {
                "ts": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "action": "browser_fallback",
                "status": "warn",
                "duration_ms": 0,
                "detail": f"{requested} -> chromium fallback: {reason[:400]}",
            }
        )
        await self.event_sink(
            "worker.browser_fallback",
            {
                "worker_id": self.assignment.worker_id,
                "requested_browser": requested,
                "effective_browser": "chromium",
                "reason": reason[:400],
            },
        )

    async def _launch_browser(self, pw: Any, browser_name: str) -> Browser:
        if browser_name == "chromium":
            return await self._launch_chromium(pw)

        try:
            if browser_name == "firefox":
                self.effective_browser = "firefox"
                return await pw.firefox.launch(headless=True)
            if browser_name == "webkit":
                self.effective_browser = "webkit"
                return await pw.webkit.launch(headless=True)
            return await self._launch_chromium(pw)
        except Error as exc:
            await self._emit_browser_fallback(browser_name, str(exc))
            return await self._launch_chromium(pw)

    async def _attach_listeners(self, page: Page) -> None:
        page.on("console", lambda msg: asyncio.create_task(self._on_console(msg.type, msg.text)))
        page.on("pageerror", lambda exc: asyncio.create_task(self._on_console("pageerror", str(exc))))
        page.on("response", lambda resp: asyncio.create_task(self._on_response(resp.status, resp.url)))

    async def _on_console(self, msg_type: str, text: str) -> None:
        if msg_type not in {"error", "warning", "pageerror"}:
            return
        await self.metric_sink(
            {
                "ts": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "action": "console",
                "status": "error" if msg_type in {"error", "pageerror"} else "warn",
                "duration_ms": 0,
                "detail": f"{msg_type}: {text[:400]}",
            }
        )

    async def _on_response(self, status_code: int, url: str) -> None:
        if status_code < 400:
            return
        await self.metric_sink(
            {
                "ts": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "action": "http_response",
                "status": "error",
                "duration_ms": 0,
                "detail": f"HTTP {status_code} {url[:400]}",
            }
        )

    async def _login(self, page: Page) -> None:
        await self.event_sink(
            "worker.started",
            {
                "worker_id": self.assignment.worker_id,
                "username": self.assignment.user.username,
                "browser": self.effective_browser,
                "os_profile": self.assignment.os_profile,
                "component": self.component,
                "guidance_loaded": bool(self.guidance_context),
            },
        )

        self._step += 1
        ts_start = perf_counter()
        if not self.target_url:
            raise Error("No target URL configured for worker login")
        await page.goto(self.target_url, wait_until="domcontentloaded", timeout=60_000)
        pre_shot = await self.screenshot_manager.capture(
            page,
            self.assignment.worker_id,
            self._step,
            "before_login",
            full_page=True,
        )
        await self.metric_sink(
            {
                "ts": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "user_id": self.assignment.user.username,
                "role": self.assignment.user.role,
                "browser": self.effective_browser,
                "os_profile": self.assignment.os_profile,
                "component": self.component,
                "action": "navigate",
                "status": "ok",
                "duration_ms": int((perf_counter() - ts_start) * 1000),
                "screenshot": pre_shot.name,
                "detail": "landing page loaded",
            }
        )

        username_selector = await self._first_visible(
            page,
            [
                "input[name='username']",
                "input[type='email']",
                "input[name='email']",
                "input[placeholder*='user' i]",
            ],
        )
        password_selector = await self._first_visible(
            page,
            [
                "input[name='password']",
                "input[type='password']",
            ],
        )
        submit_selector = await self._first_visible(
            page,
            [
                "button[type='submit']",
                "button:has-text('Sign in')",
                "button:has-text('Log in')",
                "input[type='submit']",
            ],
        )

        self._step += 1
        ts_start = perf_counter()
        if not username_selector or not password_selector:
            err = "unable to locate login inputs"
            await self.metric_sink(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "run_id": self.run_id,
                    "worker_id": self.assignment.worker_id,
                    "action": "login",
                    "status": "error",
                    "duration_ms": int((perf_counter() - ts_start) * 1000),
                    "detail": err,
                }
            )
            raise Error(err)

        await page.fill(username_selector, self.assignment.user.username)
        await page.fill(password_selector, self.assignment.user.password)
        if submit_selector:
            await page.click(submit_selector)
        else:
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Error:
            pass

        post_shot = await self.screenshot_manager.capture(
            page,
            self.assignment.worker_id,
            self._step,
            "after_login",
            full_page=True,
        )
        await self.metric_sink(
            {
                "ts": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "user_id": self.assignment.user.username,
                "role": self.assignment.user.role,
                "browser": self.effective_browser,
                "os_profile": self.assignment.os_profile,
                "component": self.component,
                "action": "login",
                "status": "ok",
                "duration_ms": int((perf_counter() - ts_start) * 1000),
                "screenshot": post_shot.name,
                "detail": "login submitted",
            }
        )

    async def _first_visible(self, page: Page, selectors: list[str]) -> str | None:
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Error:
                continue
            if count <= 0:
                continue
            try:
                if await locator.first.is_visible(timeout=1500):
                    return selector
            except Error:
                continue
        return None
