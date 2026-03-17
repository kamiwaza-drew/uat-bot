from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from uat_bot.api.live import router as live_router
from uat_bot.api.reports import router as reports_router
from uat_bot.api.runs import router as runs_router
from uat_bot.api.uat import router as uat_router
from uat_bot.api.ui import router as ui_router
from uat_bot.config import get_settings
from uat_bot.core.orchestrator import StressOrchestrator
from uat_bot.models import RunCreateRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    orchestrator = StressOrchestrator(settings)
    app.state.settings = settings
    app.state.orchestrator = orchestrator

    settings.uat_data_dir.mkdir(parents=True, exist_ok=True)
    (settings.uat_data_dir / "runs").mkdir(parents=True, exist_ok=True)

    await orchestrator.user_manager.cleanup_orphaned_users()

    if settings.uat_auto_run:
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
    app = FastAPI(title="UAT Bot", version="0.1.0", lifespan=lifespan)

    @app.get("/meta")
    async def meta():
        return {
            "service": "uat-bot",
            "status": "ok",
            "endpoints": ["/", "/healthz", "/runs", "/uat/contexts", "/docs", "/meta"],
        }

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    app.include_router(runs_router)
    app.include_router(live_router)
    app.include_router(reports_router)
    app.include_router(uat_router)
    app.include_router(ui_router)

    return app
