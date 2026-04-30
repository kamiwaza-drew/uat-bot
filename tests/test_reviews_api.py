from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient
create_app = pytest.importorskip("uat_bot.main").create_app
config_module = pytest.importorskip("uat_bot.config")


def test_review_plan_endpoint_returns_plan_and_run_config(tmp_path, monkeypatch):
    monkeypatch.setenv("UAT_DATA_DIR", str(tmp_path))
    config_module.get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/reviews/plan",
                json={
                    "target_url": "https://preview.example.test/runtime/apps/kaizen/",
                    "changed_files": [
                        "apps/kaizen/src/components/ChatComposer.tsx",
                        "apps/kaizen/src/routes/conversations/[id].tsx",
                    ],
                    "pr_title": "Improve chat workflow",
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["plan"]["component"] == "kaizen"
            assert "kaizen_chat" in payload["plan"]["scenarios"]
            assert payload["run_config"]["single_iteration"] is True
    finally:
        config_module.get_settings.cache_clear()


def test_review_summary_endpoint_reads_summary_from_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("UAT_DATA_DIR", str(tmp_path))
    config_module.get_settings.cache_clear()
    app = create_app()
    run_id = "review-run-1"
    summary_dir = tmp_path / "runs" / run_id / "analysis"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "review_summary.json").write_text(
        json.dumps(
            {
                "verdict": "warn",
                "summary": "A warning was detected.",
                "findings": [],
                "review_focus": "settings and preferences flows",
            }
        ),
        encoding="utf-8",
    )
    (summary_dir / "review_comment.md").write_text(
        "## UAT Review Verdict: WARN",
        encoding="utf-8",
    )
    try:
        with TestClient(app) as client:
            response = client.get(f"/reviews/{run_id}/summary")
            assert response.status_code == 200
            assert response.json()["verdict"] == "warn"

            comment_response = client.get(f"/reviews/{run_id}/comment")
            assert comment_response.status_code == 200
            assert "WARN" in comment_response.text
    finally:
        config_module.get_settings.cache_clear()
