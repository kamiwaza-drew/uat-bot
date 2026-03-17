#!/usr/bin/env python3
from __future__ import annotations

import sys


def main() -> int:
    # Input lines like: "target## description"
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if "##" not in line:
            continue
        target, desc = line.split("##", 1)
        target = target.strip()
        desc = desc.strip()
        if not target:
            continue
        print(f"  {target:<28} {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

