from __future__ import annotations

from types import SimpleNamespace

import pytest

from stress_tester.core.worker import Worker
from stress_tester.models import TestUser, WorkerAssignment


class FakeLocator:
    def __init__(self, visible: bool) -> None:
        self._visible = visible
        self.first = self

    async def count(self) -> int:
        return 1 if self._visible else 0

    async def is_visible(self, timeout: int = 0) -> bool:
        return self._visible


class FakeKeyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    async def press(self, key: str) -> None:
        self.pressed.append(key)


class FakePage:
    def __init__(
        self,
        *,
        url: str,
        body_text: str,
        visible_selectors: dict[str, bool],
        evaluate_result: object | None = None,
    ):
        self.url = url
        self._body_text = body_text
        self._visible_selectors = visible_selectors
        self._evaluate_result = evaluate_result
        self.keyboard = FakeKeyboard()
        self.fills: list[tuple[str, str]] = []
        self.clicks: list[str] = []
        self.goto_calls: list[str] = []
        self.wait_calls: list[str] = []

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 0) -> None:
        self.goto_calls.append(url)
        if "api/auth/login-url" in url or "/realms/" in url or "login" in url:
            self._visible_selectors["input[name='username']"] = True
            self._visible_selectors["input[name='password']"] = True

    async def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        self.wait_calls.append(state)

    async def evaluate(self, script: str):
        if self._evaluate_result is not None:
            return self._evaluate_result
        return self._body_text

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self._visible_selectors.get(selector, False))

    async def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))

    async def click(self, selector: str, timeout: int = 0) -> None:
        self.clicks.append(selector)
        if selector in {"button:has-text('Log In')", "button:has-text('Log in')"}:
            self._visible_selectors["input[name='username']"] = True
            self._visible_selectors["input[name='password']"] = True


class FakeScreenshotManager:
    def __init__(self) -> None:
        self.captures: list[dict[str, object]] = []

    async def capture(
        self,
        page,
        worker_id: str,
        step: int,
        label: str,
        full_page: bool = False,
    ):
        self.captures.append(
            {
                "worker_id": worker_id,
                "step": step,
                "label": label,
                "full_page": full_page,
                "url": page.url,
            }
        )
        return SimpleNamespace(name=f"{step:04d}_{label}.png")


def _make_worker() -> tuple[Worker, list[dict[str, object]], list[tuple[str, dict[str, object]]]]:
    metrics: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []

    async def metric_sink(row: dict[str, object]) -> None:
        metrics.append(row)

    async def event_sink(name: str, payload: dict[str, object]) -> None:
        events.append((name, payload))

    worker = Worker(
        run_id="run-1",
        assignment=WorkerAssignment(
            worker_id="worker-1",
            user=TestUser(
                username="admin",
                password="kamiwaza",
                role="viewer",
                user_id="user-1",
            ),
            browser="chromium",
            os_profile="win-chrome",
            scenarios=["kaizen_chat_seeded"],
        ),
        settings=SimpleNamespace(kamiwaza_url="http://localhost:7100"),
        screenshot_manager=FakeScreenshotManager(),
        metric_sink=metric_sink,
        event_sink=event_sink,
        component="kaizen",
        target_url="http://localhost:7100",
    )
    return worker, metrics, events


@pytest.mark.asyncio
async def test_login_skips_when_shell_is_visible_without_form():
    worker, metrics, events = _make_worker()
    page = FakePage(
        url="http://localhost:7100/",
        body_text="Loading... UAT Chat 20260327",
        visible_selectors={
            "button[title='Recent conversations']": True,
            "h3": True,
        },
    )

    await worker._login(page)

    assert page.fills == []
    assert page.clicks == []
    assert page.keyboard.pressed == []
    assert any(row["action"] == "login" and row["status"] == "skipped" for row in metrics)
    assert any(name == "worker.login_skipped" for name, _ in events)


@pytest.mark.asyncio
async def test_login_skips_when_session_disables_auth():
    worker, metrics, events = _make_worker()
    page = FakePage(
        url="http://localhost:7100/",
        body_text="Loading...",
        visible_selectors={},
        evaluate_result={"auth_enabled": False},
    )

    await worker._login(page)

    assert page.fills == []
    assert page.clicks == []
    assert page.keyboard.pressed == []
    assert any(row["action"] == "login" and row["status"] == "skipped" for row in metrics)
    assert any(name == "worker.login_skipped" for name, _ in events)


@pytest.mark.asyncio
async def test_login_clicks_expired_overlay_and_then_fills_form():
    worker, metrics, events = _make_worker()
    page = FakePage(
        url="http://localhost:7100/",
        body_text="Session Expired",
        visible_selectors={
            "button:has-text('Log In')": True,
        },
    )

    await worker._login(page)

    assert page.clicks[0] == "button:has-text('Log In')"
    assert ("input[name='username']", "admin") in page.fills
    assert ("input[name='password']", "kamiwaza") in page.fills
    assert any(row["action"] == "login" and row["status"] == "ok" for row in metrics)
    assert any(row.get("password") == "***redacted***" for row in metrics)
    assert not any(row.get("password") == "kamiwaza" for row in metrics)
    assert any(name == "worker.started" for name, _ in events)


@pytest.mark.asyncio
async def test_login_falls_back_to_auth_login_url_when_overlay_is_missing():
    worker, metrics, events = _make_worker()
    page = FakePage(
        url="http://localhost:7100/",
        body_text="Loading...",
        visible_selectors={},
        evaluate_result="http://localhost:7100/api/auth/login?redirect_uri=http://localhost:7100/",
    )

    await worker._login(page)

    assert any("api/auth/login?redirect_uri=http://localhost:7100/" in url for url in page.goto_calls)
    assert ("input[name='username']", "admin") in page.fills
    assert ("input[name='password']", "kamiwaza") in page.fills
    assert any(row["action"] == "login" and row["status"] == "ok" for row in metrics)
    assert any(name == "worker.started" for name, _ in events)


@pytest.mark.asyncio
async def test_looks_like_login_page_recognizes_auth_routes():
    worker, _, _ = _make_worker()
    page = FakePage(
        url="https://example.com/realms/master/login-actions",
        body_text="",
        visible_selectors={},
    )

    assert await worker._looks_like_login_page(page) is True
