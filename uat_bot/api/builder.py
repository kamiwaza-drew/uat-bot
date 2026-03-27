from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from uat_bot.models import (
    ScenarioGenerateRequest,
    ScenarioGenerateResponse,
    ScenarioSaveRequest,
    ScenarioSaveResponse,
)
from uat_bot.scenarios.builder import detect_backend, detect_backends, generate_scenario, _validate_parsed
from uat_bot.scenarios.explorer import explore_and_build

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/builder", tags=["builder"])


def _scenarios_dir(request: Request) -> Path:
    """Return the custom scenarios directory, creating it if needed."""
    settings = request.app.state.settings
    d = settings.uat_data_dir / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/backends")
async def list_backends():
    """Return available LLM backends and which one is active."""
    available = detect_backends()
    active = available[0] if available else None
    return {"backends": available, "active": active}


@router.post("/generate", response_model=ScenarioGenerateResponse)
async def generate(payload: ScenarioGenerateRequest):
    """Generate a scenario YAML from a natural language prompt."""
    result = generate_scenario(
        prompt=payload.prompt,
        name=payload.name,
        tags=payload.tags,
        backend=payload.backend,
    )
    return ScenarioGenerateResponse(
        yaml_content=result["yaml_content"],
        name=result["name"],
        errors=result["errors"],
        backend_used=result["backend_used"],
    )


@router.post("/save", response_model=ScenarioSaveResponse)
async def save(payload: ScenarioSaveRequest, request: Request):
    """Validate and save a scenario YAML to the custom scenarios directory."""
    try:
        parsed = yaml.safe_load(payload.yaml_content)
    except yaml.YAMLError as exc:
        return ScenarioSaveResponse(saved=False, errors=[f"YAML parse error: {exc}"])

    if not isinstance(parsed, dict):
        return ScenarioSaveResponse(saved=False, errors=["YAML did not parse to a mapping"])

    errors = _validate_parsed(parsed)
    if errors:
        return ScenarioSaveResponse(saved=False, errors=errors)

    # Sanitize name for filename
    name = payload.name.strip().replace(" ", "_").replace("/", "_")
    if not name:
        return ScenarioSaveResponse(saved=False, errors=["Name is required"])

    # Ensure parsed YAML has the name field
    parsed["name"] = parsed.get("name", name)

    scenarios_dir = _scenarios_dir(request)
    file_path = scenarios_dir / f"{name}.yaml"

    # Prevent path traversal
    resolved = file_path.resolve()
    if not resolved.is_relative_to(scenarios_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid scenario name")

    file_path.write_text(
        yaml.dump(parsed, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return ScenarioSaveResponse(saved=True, path=str(file_path))


@router.get("/scenarios")
async def list_scenarios(request: Request):
    """List user-generated scenarios from the custom directory."""
    scenarios_dir = _scenarios_dir(request)
    items = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            items.append({
                "name": raw.get("name", path.stem),
                "description": raw.get("description", ""),
                "tags": raw.get("tags", []),
                "path": str(path),
                "step_count": len(raw.get("steps", [])),
            })
        except Exception:
            items.append({
                "name": path.stem,
                "description": "(parse error)",
                "tags": [],
                "path": str(path),
                "step_count": 0,
            })
    return {"scenarios": items}


@router.post("/explore")
async def explore(request: Request):
    """Interactively explore a real app with an LLM and build a scenario.

    Streams progress as SSE events, then returns the final YAML.
    """
    body = await request.json()
    target_url = body.get("target_url", "").strip()
    task = body.get("task", "").strip()
    username = body.get("username", "admin").strip()
    password = body.get("password", "kamiwaza").strip()
    backend = body.get("backend") or detect_backend() or "claude"

    if not target_url:
        raise HTTPException(status_code=400, detail="target_url is required")
    if not task:
        raise HTTPException(status_code=400, detail="task description is required")

    import json

    queue: asyncio.Queue[str] = asyncio.Queue()
    done_event = asyncio.Event()
    result_holder: list = []

    async def on_step(step_num: int, description: str) -> None:
        await queue.put(json.dumps({"type": "step", "step": step_num, "message": description}))

    async def run_exploration() -> None:
        try:
            result = await explore_and_build(
                target_url=target_url,
                task_description=task,
                username=username,
                password=password,
                backend=backend,
                on_step=on_step,
            )
            result_holder.append(result)
            await queue.put(json.dumps({
                "type": "complete",
                "success": result.success,
                "yaml_content": result.yaml_content,
                "steps_taken": len(result.steps),
                "errors": result.errors,
                "name": _extract_name(result.yaml_content),
            }))
        except Exception as exc:
            logger.exception("Explorer failed")
            await queue.put(json.dumps({
                "type": "error",
                "message": str(exc),
            }))
        finally:
            done_event.set()

    async def event_stream():
        task = asyncio.create_task(run_exploration())
        try:
            while not done_event.is_set() or not queue.empty():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _extract_name(yaml_content: str) -> str:
    """Pull the scenario name from YAML content."""
    for line in yaml_content.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""
