from __future__ import annotations

from pathlib import Path


def list_builtin_scenarios(root: Path) -> list[Path]:
    path = root / "builtin"
    if not path.exists():
        return []
    return sorted(path.glob("*.yaml"))
