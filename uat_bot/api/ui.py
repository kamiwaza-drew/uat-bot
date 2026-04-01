from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["ui"])

_UI_FILE = Path(__file__).resolve().parents[1] / "ui" / "index.html"
_UI_DIR = _UI_FILE.parent


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def control_center() -> HTMLResponse:
    return HTMLResponse(content=_UI_FILE.read_text(encoding="utf-8"))


@router.get("/ui/assets/{asset_path:path}", include_in_schema=False)
async def ui_asset(asset_path: str):
    candidate = (_UI_DIR / asset_path).resolve()
    ui_root = _UI_DIR.resolve()
    try:
        candidate.relative_to(ui_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid asset path") from exc

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    media_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
    return FileResponse(path=candidate, media_type=media_type)
