from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

_UI_FILE = Path(__file__).resolve().parents[1] / "ui" / "index.html"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def control_center() -> HTMLResponse:
    return HTMLResponse(content=_UI_FILE.read_text(encoding="utf-8"))
