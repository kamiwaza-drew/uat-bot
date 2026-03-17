from __future__ import annotations

import asyncio
import json

from uat_bot.reporting.generator import ReportGenerator


def test_report_includes_event_logs_section(tmp_path):
    run_id = "run123"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "metrics.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-03-17T16:00:00Z",
                "worker_id": "w1",
                "action": "login",
                "status": "ok",
                "duration_ms": 123,
                "detail": "login submitted",
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-03-17T16:00:01Z",
                "run_id": run_id,
                "type": "run.started",
                "payload": {"component": "graphiti"},
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    report_path = asyncio.run(ReportGenerator().generate(run_id, run_dir))
    html = report_path.read_text(encoding="utf-8")

    assert report_path.exists()
    assert "Run/Event Logs" in html
    assert "Events Logged:</strong> 1" in html
    assert "run.started" in html
