from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ScenarioStep:
    """A single step within a scenario."""

    action: str  # navigate, click, fill, scroll, wait_for, screenshot, vision_assert
    url: str | None = None
    target: str | None = None
    value: str | None = None
    wait_for: str | None = None  # domcontentloaded, networkidle, load, or vision prompt
    timeout: int = 30  # seconds
    poll_interval: int = 2  # seconds for wait_for loops
    screenshot_name: str | None = None
    validate: list[dict[str, Any]] = field(default_factory=list)
    direction: str = "down"  # for scroll action


@dataclass
class Scenario:
    """A parsed YAML scenario with metadata and steps."""

    name: str
    description: str
    timeout: int = 300
    required_role: str = "viewer"
    tags: list[str] = field(default_factory=list)
    steps: list[ScenarioStep] = field(default_factory=list)
    source_path: str | None = None

    @property
    def is_exploratory(self) -> bool:
        return self.name == "exploratory"


def parse_scenario(raw: dict[str, Any], source_path: str | None = None) -> Scenario:
    """Parse a raw YAML dict into a Scenario object."""
    steps = []
    for step_raw in raw.get("steps", []):
        steps.append(
            ScenarioStep(
                action=step_raw["action"],
                url=step_raw.get("url"),
                target=step_raw.get("target"),
                value=step_raw.get("value"),
                wait_for=step_raw.get("wait_for"),
                timeout=step_raw.get("timeout", 30),
                poll_interval=step_raw.get("poll_interval", 2),
                screenshot_name=step_raw.get("screenshot_name"),
                validate=step_raw.get("validate", []),
                direction=step_raw.get("direction", "down"),
            )
        )

    return Scenario(
        name=raw["name"],
        description=raw.get("description", ""),
        timeout=raw.get("timeout", 300),
        required_role=raw.get("required_role", "viewer"),
        tags=raw.get("tags", []),
        steps=steps,
        source_path=source_path,
    )


def load_scenario_file(path: Path) -> Scenario:
    """Load a single scenario YAML file."""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return parse_scenario(raw, source_path=str(path))


def list_builtin_scenarios(root: Path | None = None) -> list[Path]:
    """List all built-in scenario YAML files."""
    if root is None:
        root = Path(__file__).parent
    path = root / "builtin"
    if not path.exists():
        return []
    return sorted(path.glob("*.yaml"))


def load_all_scenarios(
    custom_dirs: list[Path] | None = None,
) -> dict[str, Scenario]:
    """Load all scenarios from builtin and custom directories."""
    scenarios: dict[str, Scenario] = {}

    # Load built-in scenarios
    for path in list_builtin_scenarios():
        scenario = load_scenario_file(path)
        scenarios[scenario.name] = scenario

    # Load custom scenarios (override built-in if same name)
    for custom_dir in custom_dirs or []:
        if not custom_dir.exists():
            continue
        for path in sorted(custom_dir.glob("*.yaml")):
            scenario = load_scenario_file(path)
            scenarios[scenario.name] = scenario

    return scenarios


def pick_scenario(
    available: dict[str, Scenario],
    assigned_names: list[str],
    weights: dict[str, int] | None = None,
    user_role: str = "viewer",
) -> Scenario | None:
    """Pick a scenario from the assigned list, respecting weights and role."""
    # Role hierarchy: admin > editor > viewer
    role_level = {"admin": 3, "editor": 2, "viewer": 1, "user": 2}
    user_level = role_level.get(user_role, 1)

    eligible = []
    scenario_weights = []
    for name in assigned_names:
        scenario = available.get(name)
        if scenario is None:
            continue
        required_level = role_level.get(scenario.required_role, 1)
        if user_level >= required_level:
            eligible.append(scenario)
            scenario_weights.append(weights.get(name, 1) if weights else 1)

    if not eligible:
        return None

    return random.choices(eligible, weights=scenario_weights, k=1)[0]
