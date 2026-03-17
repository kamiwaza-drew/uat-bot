from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/report", tags=["report"])


@router.get("/health")
async def report_health():
    return {"ok": True}
