#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    # Prefer kamiwaza.json version (aligns with extension publishing), fallback to pyproject.toml.
    kamiwaza_json = Path("kamiwaza.json")
    if kamiwaza_json.exists():
        data = json.loads(kamiwaza_json.read_text(encoding="utf-8"))
        version = data.get("version")
        if isinstance(version, str) and version.strip():
            print(version.strip())
            return 0

    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("version"):
                # naive but adequate: version = "x.y.z"
                parts = line.split("=", 1)
                if len(parts) == 2:
                    v = parts[1].strip().strip('"').strip("'")
                    if v:
                        print(v)
                        return 0

    raise SystemExit("Unable to determine version (missing kamiwaza.json and pyproject.toml version)")


if __name__ == "__main__":
    raise SystemExit(main())

