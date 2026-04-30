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
from uat_bot.scenarios.loader import Scenario, load_all_scenarios, pick_scenario
from uat_bot.scenarios.runner import ScenarioRunner

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
        vision_client: Any | None = None,
        scenario_weights: dict[str, int] | None = None,
        single_iteration: bool = False,
        test_message: str | None = None,
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
        self.vision_client = vision_client
        self.scenario_weights = scenario_weights or {}
        self.single_iteration = single_iteration
        self.test_message = test_message or ""
        self._step = 0
        self.effective_browser = assignment.browser

    @property
    def _user_context(self) -> dict[str, str]:
        """Context dict passed to scenario runner for placeholder resolution."""
        return {
            "ts": datetime.now(UTC).isoformat(),
            "user_id": self.assignment.user.username,
            "username": self.assignment.user.username,
            "password": self.assignment.user.password,
            "role": self.assignment.user.role,
            "browser": self.effective_browser,
            "os_profile": self.assignment.os_profile,
            "component": self.component or "",
            "test_message": self.test_message,
        }

    @property
    def _metric_context(self) -> dict[str, str]:
        context = dict(self._user_context)
        if context.get("password"):
            context["password"] = "***redacted***"
        return context

    async def run(self, duration_seconds: int, cancel_event: asyncio.Event) -> None:
        started = perf_counter()
        profile = get_profile(self.assignment.os_profile)

        # Load all available scenarios
        available_scenarios = load_all_scenarios(
            [self.settings.uat_data_dir / "scenarios"]
        )

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

                # Always login first
                await self._login(page)

                # Run assigned scenarios in a loop until duration expires
                while perf_counter() - started < duration_seconds and not cancel_event.is_set():
                    scenario = pick_scenario(
                        available=available_scenarios,
                        assigned_names=self.assignment.scenarios,
                        weights=self.scenario_weights,
                        user_role=self.assignment.user.role,
                    )

                    if scenario is None:
                        # No eligible scenarios — fall back to heartbeat
                        await self._heartbeat(page)
                        await asyncio.sleep(5)
                        continue

                    if scenario.name == "login":
                        # Already logged in, skip re-login scenario
                        await asyncio.sleep(2)
                        continue

                    # Calculate remaining time
                    elapsed = perf_counter() - started
                    remaining = max(10, duration_seconds - elapsed)

                    runner = ScenarioRunner(
                        page=page,
                        scenario=scenario,
                        screenshot_manager=self.screenshot_manager,
                        worker_id=self.assignment.worker_id,
                        run_id=self.run_id,
                        user_context=self._user_context,
                        metric_sink=self.metric_sink,
                        event_sink=self.event_sink,
                        base_url=self.target_url,
                        vision_client=self.vision_client,
                        guidance_context=self.guidance_context,
                        step_offset=self._step,
                    )

                    try:
                        results = await asyncio.wait_for(
                            runner.run(cancel_event=cancel_event),
                            timeout=min(remaining, scenario.timeout),
                        )
                        self._step = runner.step_counter
                    except asyncio.TimeoutError:
                        self._step = runner.step_counter
                        await self.metric_sink(
                            {
                                **self._metric_context,
                                "run_id": self.run_id,
                                "worker_id": self.assignment.worker_id,
                                "action": "scenario_timeout",
                                "status": "error",
                                "duration_ms": int((perf_counter() - started) * 1000),
                                "detail": f"scenario {scenario.name} timed out",
                            }
                        )

                    # In single_iteration mode, stop after one scenario pass
                    if self.single_iteration:
                        break

                    # Think time between scenarios (simulate human)
                    if not cancel_event.is_set():
                        await asyncio.sleep(2)

            finally:
                await context.close()
                await browser.close()

    async def _heartbeat(self, page: Page) -> None:
        """Capture a heartbeat screenshot when no scenarios are available."""
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
                **self._metric_context,
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "action": "heartbeat",
                "status": "ok",
                "duration_ms": duration_ms,
                "screenshot": shot_path.name,
                "detail": "steady-state capture",
            }
        )
        await self.event_sink(
            "worker.screenshot",
            {
                "worker_id": self.assignment.worker_id,
                "screenshot": shot_path.relative_to(self.screenshot_manager.run_dir).as_posix(),
            },
        )

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
        """Perform initial login using the built-in login flow."""
        await self.event_sink(
            "worker.started",
            {
                "worker_id": self.assignment.worker_id,
                "username": self.assignment.user.username,
                "browser": self.effective_browser,
                "os_profile": self.assignment.os_profile,
                "component": self.component,
                "guidance_loaded": bool(self.guidance_context),
                "scenarios": self.assignment.scenarios,
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
                **self._metric_context,
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "action": "navigate",
                "status": "ok",
                "duration_ms": int((perf_counter() - ts_start) * 1000),
                "screenshot": pre_shot.name,
                "detail": "landing page loaded",
            }
        )

        # Local dev mode can disable auth entirely. If the session endpoint
        # says auth is disabled, skip the login flow and continue with the app.
        try:
            session_info = await page.evaluate(
                """async () => {
                    try {
                        const resp = await fetch('/api/session', { credentials: 'include' });
                        if (!resp.ok) return null;
                        return await resp.json();
                    } catch {
                        return null;
                    }
                }"""
            )
        except Error:
            session_info = None

        if isinstance(session_info, dict) and session_info.get("auth_enabled") is False:
            self._step += 1
            ts_start = perf_counter()
            post_shot = await self.screenshot_manager.capture(
                page,
                self.assignment.worker_id,
                self._step,
                "after_login",
                full_page=True,
            )
            await self.metric_sink(
                {
                    **self._metric_context,
                    "run_id": self.run_id,
                    "worker_id": self.assignment.worker_id,
                    "action": "login",
                    "status": "skipped",
                    "duration_ms": int((perf_counter() - ts_start) * 1000),
                    "screenshot": post_shot.name,
                    "detail": "auth disabled; skipping login",
                }
            )
            await self.event_sink(
                "worker.login_skipped",
                {
                    "worker_id": self.assignment.worker_id,
                    "reason": "auth disabled in session response",
                    "url": page.url,
                },
            )
            return

        # Handle consent gate if present
        from uat_bot.browser.actions import resolve_selector

        consent_sel = await resolve_selector(page, "consent_accept")
        if consent_sel:
            try:
                await page.click(consent_sel, timeout=3000)
                await asyncio.sleep(1)
            except Error:
                pass  # No consent gate, continue

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

        if not username_selector or not password_selector:
            login_button_selector = await self._first_visible(
                page,
                [
                    "button:has-text('Log In')",
                    "button:has-text('Log in')",
                ],
            )
            if login_button_selector:
                await page.click(login_button_selector)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                except Error:
                    pass
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

        if not username_selector or not password_selector:
            login_url = None
            try:
                login_url = await page.evaluate(
                    """async () => {
                        try {
                          const resp = await fetch(`/api/auth/login-url?redirect_uri=${encodeURIComponent(window.location.href)}`, { credentials: 'include' });
                          if (!resp.ok) return null;
                          const data = await resp.json();
                          return typeof data?.login_url === 'string' ? data.login_url : null;
                        } catch {
                          return null;
                        }
                    }"""
                )
            except Error:
                login_url = None

            if login_url:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                except Error:
                    pass
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

        if not username_selector or not password_selector:
            # Some local Kaizen deployments intentionally run with auth disabled.
            # In that mode the app shell is already visible and no login form is
            # rendered, so treat the session as authenticated and keep going.
            # The app can render a loading shell first and then hydrate into the
            # real agent dashboard a moment later, so give it a short grace
            # period before declaring the session unauthenticated.
            for _ in range(10):
                try:
                    await page.wait_for_load_state("networkidle", timeout=1_500)
                except Error:
                    pass
                if await self._looks_like_app_shell(page) or not await self._looks_like_login_page(page):
                    self._step += 1
                    ts_start = perf_counter()
                    post_shot = await self.screenshot_manager.capture(
                        page,
                        self.assignment.worker_id,
                        self._step,
                        "after_login",
                        full_page=True,
                    )
                    await self.metric_sink(
                        {
                            **self._metric_context,
                            "run_id": self.run_id,
                            "worker_id": self.assignment.worker_id,
                            "action": "login",
                            "status": "skipped",
                            "duration_ms": int((perf_counter() - ts_start) * 1000),
                            "screenshot": post_shot.name,
                            "detail": "login form not present; app shell detected",
                        }
                    )
                    await self.event_sink(
                        "worker.login_skipped",
                        {
                            "worker_id": self.assignment.worker_id,
                            "reason": "no login form and app shell or non-auth page detected",
                            "url": page.url,
                        },
                    )
                    return
                await asyncio.sleep(1)

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
                    **self._metric_context,
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

        # Detect Keycloak redirect (ForwardAuth sends to /realms/...)
        is_keycloak = "/realms/" in page.url
        if is_keycloak:
            await self.metric_sink(
                {
                    **self._metric_context,
                    "run_id": self.run_id,
                    "worker_id": self.assignment.worker_id,
                    "action": "keycloak_redirect",
                    "status": "ok",
                    "duration_ms": int((perf_counter() - ts_start) * 1000),
                    "detail": f"Keycloak login page detected: {page.url}",
                }
            )

        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Error:
            pass

        # If Keycloak login, wait for redirect back to the extension/app URL
        if is_keycloak:
            try:
                await page.wait_for_url(
                    lambda url: "/realms/" not in url,
                    timeout=30_000,
                )
            except Error:
                pass  # May already be redirected

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
        login_detail = "login submitted"
        if is_keycloak:
            login_detail = f"Keycloak login completed, redirected to {page.url}"
        await self.metric_sink(
            {
                **self._metric_context,
                "run_id": self.run_id,
                "worker_id": self.assignment.worker_id,
                "action": "login",
                "status": "ok",
                "duration_ms": int((perf_counter() - ts_start) * 1000),
                "screenshot": post_shot.name,
                "detail": login_detail,
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

    async def _looks_like_app_shell(self, page: Page) -> bool:
        """Return True when the loaded page already looks like the app shell."""
        try:
            body_text = await page.evaluate(
                "document.body ? (document.body.innerText || '') : ''"
            )
        except Error:
            return False

        haystack = body_text.lower()
        markers = (
            "agents",
            "conversations",
            "search",
            "create new agent",
            "recipes",
            "workroom",
        )
        if any(marker in haystack for marker in markers):
            return True

        # The Kaizen shell renders visible cards and a recent conversations rail
        # even before the client finishes hydrating, so treat that structure as a
        # valid authenticated landing surface too.
        return (
            await self._first_visible(
                page,
                [
                    "button[title='Recent conversations']",
                    "h3",
                    "[data-testid='conversation-list']",
                ],
            )
            is not None
        )

    async def _looks_like_login_page(self, page: Page) -> bool:
        """Return True when the page still appears to be an auth surface."""
        url = page.url.lower()
        if any(marker in url for marker in ("/login", "/signin", "/sign-in", "/auth", "/realms/")):
            return True

        try:
            body_text = await page.evaluate(
                "document.body ? (document.body.innerText || '') : ''"
            )
        except Error:
            return False

        haystack = body_text.lower()
        login_markers = (
            "sign in",
            "log in",
            "login",
            "keycloak",
            "authenticate",
        )
        return any(marker in haystack for marker in login_markers)
