from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("stress_tester.main").create_app
builder_api = pytest.importorskip("stress_tester.api.builder")


def test_builder_explore_stream_includes_log_events(monkeypatch):
    async def fake_explore_and_build(
        target_url: str,
        task_description: str,
        username: str = "admin",
        password: str = "kamiwaza",
        backend: str = "claude",
        max_steps: int = 25,
        on_step=None,
        on_event=None,
    ):
        if on_step:
            await on_step(2, "Exploring step 1")
        if on_event:
            await on_event(
                {
                    "type": "log",
                    "event": "think.response",
                    "message": "Model proposed next action",
                    "payload": {"raw_response": '{"type":"click","selector":"button.save"}'},
                    "ts": "2026-04-01T00:00:00+00:00",
                }
            )
        return SimpleNamespace(
            success=True,
            yaml_content="name: generated_scenario\nsteps: []\n",
            errors=[],
            steps=[SimpleNamespace()],
        )

    monkeypatch.setattr(builder_api, "explore_and_build", fake_explore_and_build)

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/builder/explore",
            json={
                "target_url": "https://example.test/app",
                "task": "click save",
                "username": "admin",
                "password": "pw",
                "backend": "claude",
            },
        )
        assert response.status_code == 200
        body = response.text
        assert '"type": "log"' in body
        assert '"event": "session.start"' in body
        assert '"event": "think.response"' in body
        assert '"type": "complete"' in body


def test_builder_explore_uses_kubectl_secret_when_password_is_blank(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_explore_and_build(
        target_url: str,
        task_description: str,
        username: str = "admin",
        password: str = "kamiwaza",
        backend: str = "claude",
        max_steps: int = 25,
        on_step=None,
        on_event=None,
    ):
        captured["username"] = username
        captured["password"] = password
        return SimpleNamespace(
            success=True,
            yaml_content="name: generated_scenario\nsteps: []\n",
            errors=[],
            steps=[],
        )

    monkeypatch.setattr(builder_api, "explore_and_build", fake_explore_and_build)
    monkeypatch.setattr(
        builder_api.KamiwazaUserManager,
        "_kubectl_admin_password",
        staticmethod(lambda: "secret-pass"),
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/builder/explore",
            json={
                "target_url": "https://example.test/app",
                "task": "click save",
                "username": "",
                "password": None,
                "backend": "claude",
            },
        )

    assert response.status_code == 200
    assert captured == {"username": "admin", "password": "secret-pass"}
