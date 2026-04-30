from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from uat_bot.models import ReviewRunRequest

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _orchestrator(request: Request):
    return request.app.state.orchestrator


@router.post("/plan")
async def preview_review_plan(payload: ReviewRunRequest, request: Request):
    orchestrator = _orchestrator(request)
    plan = orchestrator.review_planner.build_plan(payload)
    run_config = orchestrator.review_planner.build_run_request(payload, plan)
    return {
        "request": orchestrator._redacted_review_request(payload.model_dump(mode="json")),
        "plan": plan.model_dump(mode="json"),
        "run_config": orchestrator._redacted_config(run_config.model_dump(mode="json")),
    }


@router.post("")
async def create_review_run(payload: ReviewRunRequest, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.start_review(payload)
    return orchestrator.detail(state)


@router.get("/{run_id}/summary")
async def get_review_summary(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)
    if state and state.review_summary:
        return JSONResponse(content=state.review_summary.model_dump(mode="json"))

    run_dir = orchestrator.settings.uat_data_dir / "runs" / run_id
    summary_path = run_dir / "analysis" / "review_summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Review summary not found")
    return JSONResponse(content=json.loads(summary_path.read_text(encoding="utf-8")))


@router.get("/{run_id}/comment", response_class=PlainTextResponse)
async def get_review_comment(run_id: str, request: Request):
    orchestrator = _orchestrator(request)
    state = await orchestrator.get_run(run_id)
    if state and state.review_summary:
        return PlainTextResponse(content=state.review_summary.comment_markdown)

    run_dir = orchestrator.settings.uat_data_dir / "runs" / run_id
    comment_path = run_dir / "analysis" / "review_comment.md"
    if not comment_path.exists():
        raise HTTPException(status_code=404, detail="Review comment not found")
    return PlainTextResponse(content=comment_path.read_text(encoding="utf-8"))
