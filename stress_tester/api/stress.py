from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/stress", tags=["stress"])


def _orchestrator(request: Request):
    return request.app.state.orchestrator


@router.get("/contexts")
async def list_stress_contexts(
    request: Request,
    component: str | None = Query(default=None),
):
    orchestrator = _orchestrator(request)
    loader = orchestrator.uat_context_loader
    bundle = loader.load_bundle(component=component)
    return {
        "component": component,
        "source_dirs": bundle.source_dirs,
        "files": bundle.file_paths,
        "doc_count": len(bundle.docs),
    }
