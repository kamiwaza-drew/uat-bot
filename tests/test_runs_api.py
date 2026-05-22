from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("stress_tester.main").create_app
config_module = pytest.importorskip("stress_tester.config")


def _payload() -> dict:
    return {
        "concurrent_users": 1,
        "role_distribution": {"viewer": 1},
        "browser_distribution": {"chromium": 1},
        "os_emulation": ["win-chrome"],
        "scenarios": ["login"],
        "duration_seconds": 10,
        "ramp_up_seconds": 0,
        "vision_enabled": False,
    }


def test_purge_run_removes_run_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("STRESS_TESTER_DATA_DIR", str(tmp_path))
    config_module.get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            create_resp = client.post("/runs", json=_payload())
            assert create_resp.status_code == 200
            run_id = create_resp.json()["run_id"]

            run_dir = tmp_path / "runs" / run_id
            assert run_dir.exists()
            (run_dir / "marker.txt").write_text("x", encoding="utf-8")

            purge_resp = client.delete(f"/runs/{run_id}/purge")
            assert purge_resp.status_code == 200
            assert purge_resp.json() == {"run_id": run_id, "deleted": True}
            assert not run_dir.exists()

            runs_resp = client.get("/runs")
            run_ids = [row["run_id"] for row in runs_resp.json()]
            assert run_id not in run_ids
    finally:
        config_module.get_settings.cache_clear()


def test_purge_missing_run_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv("STRESS_TESTER_DATA_DIR", str(tmp_path))
    config_module.get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            purge_resp = client.delete("/runs/not-a-real-run/purge")
            assert purge_resp.status_code == 404
    finally:
        config_module.get_settings.cache_clear()


def test_snapshot_includes_metrics_events_and_screenshots(tmp_path, monkeypatch):
    monkeypatch.setenv("STRESS_TESTER_DATA_DIR", str(tmp_path))
    config_module.get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            create_resp = client.post("/runs", json=_payload())
            assert create_resp.status_code == 200
            run_id = create_resp.json()["run_id"]

            run_dir = tmp_path / "runs" / run_id
            (run_dir / "metrics.jsonl").write_text('{"action":"login","status":"ok"}\n', encoding="utf-8")
            (run_dir / "events.jsonl").write_text('{"type":"run.started","payload":{"x":1}}\n', encoding="utf-8")
            shots_dir = run_dir / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / "shot-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

            snapshot_resp = client.get(f"/runs/{run_id}/snapshot")
            assert snapshot_resp.status_code == 200
            payload = snapshot_resp.json()
            assert payload["run_id"] == run_id
            assert payload["metrics"][0]["action"] == "login"
            assert payload["events"][0]["type"] == "run.started"
            assert "screenshots/shot-1.png" in payload["screenshots"]
    finally:
        config_module.get_settings.cache_clear()
