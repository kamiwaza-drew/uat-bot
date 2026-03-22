from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request

from uat_bot.models import (
    ScenarioGenerateRequest,
    ScenarioGenerateResponse,
    ScenarioSaveRequest,
    ScenarioSaveResponse,
)
from uat_bot.scenarios.builder import detect_backend, generate_scenario, _validate_parsed

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
    active = detect_backend()
    backends = []
    if active:
        backends.append(active)
    return {"backends": backends, "active": active}


@router.post("/generate", response_model=ScenarioGenerateResponse)
async def generate(payload: ScenarioGenerateRequest):
    """Generate a scenario YAML from a natural language prompt."""
    result = generate_scenario(
        prompt=payload.prompt,
        name=payload.name,
        tags=payload.tags,
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
