#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXCLUDE_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "data",
    "build",
    "dist",
}

EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _copytree_ignore(_src: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in EXCLUDE_NAMES:
            ignored.add(name)
            continue
        if any(name.endswith(suffix) for suffix in EXCLUDE_SUFFIXES):
            ignored.add(name)
            continue
    return ignored


def _run(cmd: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.run(cmd, cwd=str(cwd), check=False, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def _run_template_python(template_repo: Path, script_and_args: list[str]) -> None:
    _run(
        ["uv", "run", "--project", str(template_repo), "python", *script_and_args],
        cwd=template_repo,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy this uat-bot folder into a kamiwaza-extensions-template repo as an app extension."
    )
    parser.add_argument(
        "--template-repo",
        default="/home/ec2-user/k8s/kamiwaza-extensions-template",
        help="Path to kamiwaza-extensions-template repo clone",
    )
    parser.add_argument(
        "--app-name",
        default="uat-bot",
        help="App directory name under apps/",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing apps/<app-name> if present",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip running template sync/validation/build-registry checks after copy",
    )
    args = parser.parse_args()

    source_root = Path(__file__).resolve().parents[1]
    template_repo = Path(args.template_repo).resolve()
    destination = template_repo / "apps" / args.app_name

    if not (template_repo / "scripts" / "build-registry.py").exists():
        print(f"Error: template repo not found or invalid at: {template_repo}", file=sys.stderr)
        return 1

    if destination.exists():
        if not args.force:
            print(
                f"Error: destination already exists: {destination}\n"
                "Use --force to replace it.",
                file=sys.stderr,
            )
            return 1
        shutil.rmtree(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, destination, ignore=_copytree_ignore)

    print(f"Copied {source_root} -> {destination}")

    if args.skip_validate:
        return 0

    print("Running template sync/validation/build-registry checks...")
    _run_template_python(
        template_repo,
        ["scripts/sync-compose.py", "--type", "app", "--name", args.app_name],
    )
    _run_template_python(
        template_repo,
        ["scripts/validate-metadata.py", "--type", "app", "--name", args.app_name],
    )
    _run_template_python(
        template_repo,
        ["scripts/validate-compose.py", "--type", "app", "--name", args.app_name],
    )
    _run_template_python(
        template_repo,
        ["scripts/build-registry.py", "--stage", "dev", "--repo-version", "2"],
    )
    print("Template checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
