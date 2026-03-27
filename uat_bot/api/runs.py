from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from uat_bot.models import RunCreateRequest
from uat_bot.reporting.analyzer import RunAnalyzer

router = APIRouter(prefix="/runs", tags=["runs"])


def _orchestrator(request: Request):
    return request.app.state.orchestrator


@router.post("")
async def create_run(payload: RunCreateRequest, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.start_run(payload)
    return orchestrator.detail(state)


@router.get("")
async def list_runs(request: Request):
    orchestrator = _orchestrator(request)
    return await orchestrator.list_runs()


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    return orchestrator.detail(state)


@router.delete("/{run_id}")
async def delete_run(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    deleted = await orchestrator.stop_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    state = await orchestrator.get_run(run_id)
    if not state:
        return {"run_id": run_id, "status": "CANCELLED"}
    return orchestrator.detail(state)


@router.delete("/{run_id}/purge")
async def purge_run(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    purged = await orchestrator.purge_run(run_id)
    if not purged:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "deleted": True}


def _resolve_run_dir(run_id: str, request: Request) -> Path | None:
    """Resolve the run directory from in-memory state or fallback to disk."""
    orchestrator = _orchestrator(request)
    import asyncio

    loop = asyncio.get_event_loop()
    # Try in-memory state first (can't await here, use sync check)
    state = orchestrator._runs.get(run_id)
    if state:
        return state.root_dir
    # Fallback: check disk
    data_dir = orchestrator.settings.uat_data_dir / "runs" / run_id
    if data_dir.exists():
        return data_dir
    return None


@router.get("/{run_id}/report", response_class=HTMLResponse)
async def get_report(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)

    if state:
        report_path = state.report_path
        if not report_path or not report_path.exists():
            report_path = await orchestrator.reporter.generate(run_id, state.root_dir)
            state.report_path = report_path
        return HTMLResponse(content=report_path.read_text(encoding="utf-8"))

    # Fallback: serve from disk for historical runs
    run_dir = _resolve_run_dir(run_id, request)
    if not run_dir:
        raise HTTPException(status_code=404, detail="Run not found")

    report_path = run_dir / "report.html"
    if not report_path.exists():
        report_path = await orchestrator.reporter.generate(run_id, run_dir)
    return HTMLResponse(content=report_path.read_text(encoding="utf-8"))


@router.post("/{run_id}/analyze")
async def analyze_run(run_id: str, request: Request):
    """Run (or re-run) AI analysis on a completed run's screenshots."""
    orchestrator = _orchestrator(request)

    run_dir = _resolve_run_dir(run_id, request)
    if not run_dir:
        raise HTTPException(status_code=404, detail="Run not found")

    analyzer = RunAnalyzer()
    if not analyzer.backend:
        raise HTTPException(
            status_code=400,
            detail="No LLM backend available. Install claude or codex CLI.",
        )
    analysis = await analyzer.analyze_run(run_dir)

    # Regenerate report with analysis baked in
    state = await orchestrator.get_run(run_id)
    report_path = await orchestrator.reporter.generate(run_id, run_dir, ai_analysis=analysis)
    if state:
        state.report_path = report_path

    return JSONResponse(
        content={
            "run_id": run_id,
            "overall_verdict": analysis.overall_verdict,
            "executive_summary": analysis.executive_summary,
            "pass_count": analysis.pass_count,
            "fail_count": analysis.fail_count,
            "warn_count": analysis.warn_count,
            "report_url": f"/runs/{run_id}/report",
        }
    )


@router.get("/{run_id}/artifacts/{artifact_path:path}")
async def get_artifact(run_id: str, artifact_path: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)

    if state:
        run_dir = state.root_dir
    else:
        run_dir = _resolve_run_dir(run_id, request)
        if not run_dir:
            raise HTTPException(status_code=404, detail="Run not found")

    candidate = (run_dir / artifact_path).resolve()
    root = run_dir.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    media_type = None
    if candidate.suffix.lower() == ".html":
        media_type = "text/html"
    elif candidate.suffix.lower() in {".png"}:
        media_type = "image/png"
    elif candidate.suffix.lower() in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"

    return FileResponse(path=Path(candidate), media_type=media_type)
