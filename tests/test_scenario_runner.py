from __future__ import annotations

import pytest

from uat_bot.scenarios.loader import Scenario, ScenarioStep
from uat_bot.scenarios.runner import ScenarioRunner, StepResult


@pytest.mark.asyncio
async def test_scenario_metrics_redact_password(monkeypatch):
    metrics: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []

    async def metric_sink(row: dict[str, object]) -> None:
        metrics.append(row)

    async def event_sink(name: str, payload: dict[str, object]) -> None:
        events.append((name, payload))

    async def fake_execute_step(self, index: int, step: ScenarioStep) -> StepResult:
        return StepResult(step_index=index, action=step.action, status="ok", duration_ms=1)

    monkeypatch.setattr(ScenarioRunner, "_execute_step", fake_execute_step)

    runner = ScenarioRunner(
        page=None,
        scenario=Scenario(
            name="redaction_probe",
            description="",
            steps=[ScenarioStep(action="wait_for", target="body")],
        ),
        screenshot_manager=None,
        worker_id="worker-1",
        run_id="run-1",
        user_context={"username": "admin", "password": "real-secret"},
        metric_sink=metric_sink,
        event_sink=event_sink,
        base_url="https://example.test",
    )

    await runner.run()

    assert metrics[0]["password"] == "***redacted***"
    assert not any(row.get("password") == "real-secret" for row in metrics)
    assert any(name == "scenario.finished" for name, _ in events)
