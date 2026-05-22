from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["live"])


@router.websocket("/live/{run_id}")
async def live_updates(websocket: WebSocket, run_id: str):
    await websocket.accept()

    orchestrator = websocket.app.state.orchestrator

    state = await orchestrator.get_run(run_id)
    if not state:
        await websocket.send_json({"error": "run_not_found", "run_id": run_id})
        await websocket.close(code=4404)
        return

    await websocket.send_json({"type": "connected", "run_id": run_id})

    try:
        while True:
            event = await orchestrator.stream_event(run_id, timeout=1.0)
            if event:
                await websocket.send_json(event.model_dump(mode="json"))
            else:
                await websocket.send_json({"type": "heartbeat", "run_id": run_id})

            state = await orchestrator.get_run(run_id)
            if not state:
                await websocket.send_json({"type": "run.gone", "run_id": run_id})
                break
            if state.status.value in {"COMPLETED", "FAILED", "CANCELLED"} and state.task and state.task.done():
                await websocket.send_json({"type": "stream.complete", "run_id": run_id})
                break
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
