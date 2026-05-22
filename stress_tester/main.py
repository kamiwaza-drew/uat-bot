from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from stress_tester.api.builder import router as builder_router
from stress_tester.api.live import router as live_router
from stress_tester.api.reviews import router as reviews_router
from stress_tester.api.runs import router as runs_router
from stress_tester.api.stress import router as stress_router
from stress_tester.api.ui import router as ui_router
from stress_tester.config import get_settings
from stress_tester.core.orchestrator import StressOrchestrator
from stress_tester.models import RunCreateRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    orchestrator = StressOrchestrator(settings)
    app.state.settings = settings
    app.state.orchestrator = orchestrator

    settings.stress_tester_data_dir.mkdir(parents=True, exist_ok=True)
    (settings.stress_tester_data_dir / "runs").mkdir(parents=True, exist_ok=True)
    (settings.stress_tester_data_dir / "scenarios").mkdir(parents=True, exist_ok=True)

    await orchestrator.user_manager.cleanup_orphaned_users()

    if settings.stress_tester_auto_run:
        default_config = RunCreateRequest(
            concurrent_users=1,
            role_distribution={"viewer": 1},
            browser_distribution={"chromium": 1},
            os_emulation=["win-chrome"],
            scenarios=["login"],
            duration_seconds=30,
            ramp_up_seconds=0,
            vision_enabled=False,
        )
        await orchestrator.start_run(default_config)

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Stress Tester", version="0.1.0", lifespan=lifespan)

    @app.get("/meta")
    async def meta():
        return {
            "service": "stress-tester",
            "status": "ok",
            "endpoints": ["/", "/healthz", "/runs", "/reviews", "/stress/contexts", "/docs", "/meta"],
        }

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    app.include_router(runs_router)
    app.include_router(reviews_router)
    app.include_router(live_router)
    app.include_router(stress_router)
    app.include_router(builder_router)
    app.include_router(ui_router)

    return app
