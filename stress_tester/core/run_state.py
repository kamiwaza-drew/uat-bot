from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stress_tester.models import (
    ReviewPlan,
    ReviewRunRequest,
    ReviewSummary,
    RunCreateRequest,
    RunEvent,
    RunStatus,
    TestUser,
    UATGuidanceBundle,
)


@dataclass(slots=True)
class RunState:
    run_id: str
    config: RunCreateRequest
    root_dir: Path
    status: RunStatus = RunStatus.pending
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    ended_at: datetime | None = None
    progress_pct: float = 0.0
    completed_workers: int = 0
    failed_workers: int = 0
    errors: list[str] = field(default_factory=list)
    users: list[TestUser] = field(default_factory=list)
    report_path: Path | None = None
    metrics_path: Path | None = None
    event_log_path: Path | None = None
    uat_guidance: UATGuidanceBundle | None = None
    effective_kamiwaza_url: str | None = None
    auth_source: str | None = None
    review_request: ReviewRunRequest | None = None
    review_plan: ReviewPlan | None = None
    review_summary: ReviewSummary | None = None
    _task: asyncio.Task[Any] | None = None
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    _events: asyncio.Queue[RunEvent] = field(default_factory=asyncio.Queue)
    _event_log_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def set_task(self, task: asyncio.Task[Any]) -> None:
        self._task = task

    @property
    def task(self) -> asyncio.Task[Any] | None:
        return self._task

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def cancel_event(self) -> asyncio.Event:
        return self._cancel_event

    def request_cancel(self) -> None:
        self._cancel_event.set()

    async def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = RunEvent(ts=datetime.now(UTC), run_id=self.run_id, type=event_type, payload=payload or {})
        await self._events.put(event)
        if self.event_log_path is None:
            return
        async with self._event_log_lock:
            with self.event_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=True) + "\n")

    async def next_event(self, timeout: float = 1.0) -> RunEvent | None:
        try:
            return await asyncio.wait_for(self._events.get(), timeout=timeout)
        except TimeoutError:
            return None
