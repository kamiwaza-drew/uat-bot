from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse

from uat_bot.models import RunCreateRequest

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


@router.get("/{run_id}/report", response_class=HTMLResponse)
async def get_report(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")

    report_path = state.report_path
    if not report_path or not report_path.exists():
        report_path = await orchestrator.reporter.generate(run_id, state.root_dir)
        state.report_path = report_path

    return HTMLResponse(content=report_path.read_text(encoding="utf-8"))


@router.get("/{run_id}/artifacts/{artifact_path:path}")
async def get_artifact(run_id: str, artifact_path: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")

    candidate = (state.root_dir / artifact_path).resolve()
    root = state.root_dir.resolve()
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
