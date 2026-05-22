from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("stress_tester.main").create_app


def test_root_route_serves_ui():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Stress Tester Control Center" in response.text
        assert "Scenario Paths" in response.text
        assert "Review Run" in response.text


def test_meta_contains_root_endpoint():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/meta")
        assert response.status_code == 200
        payload = response.json()
        assert "/" in payload["endpoints"]


def test_ui_assets_route_serves_javascript():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/ui/assets/app.js")
        assert response.status_code == 200
        assert "switchPage" in response.text
