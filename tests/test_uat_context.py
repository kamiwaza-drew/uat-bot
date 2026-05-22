from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stress_tester.scenarios.uat_context import UATContextLoader


def _settings(extension_roots: str, max_files: int = 12, max_chars: int = 4000):
    return SimpleNamespace(
        stress_tester_extension_roots=extension_roots,
        stress_tester_guidance_max_files=max_files,
        stress_tester_guidance_max_chars_per_file=max_chars,
    )


def test_discover_uat_dirs_filters_by_component(tmp_path: Path):
    repo_a = tmp_path / "kamiwaza-extensions-alpha"
    repo_b = tmp_path / "kamiwaza-extensions-beta"
    (repo_a / ".uat").mkdir(parents=True)
    (repo_b / ".uat").mkdir(parents=True)

    settings = _settings(str(tmp_path / "kamiwaza-extensions-*"))
    loader = UATContextLoader(settings)

    all_dirs = loader.discover_uat_dirs()
    assert len(all_dirs) == 2

    alpha_dirs = loader.discover_uat_dirs(component="alpha")
    assert len(alpha_dirs) == 1
    assert alpha_dirs[0].parent.name == "kamiwaza-extensions-alpha"


def test_load_bundle_reads_supported_files_and_limits(tmp_path: Path):
    repo = tmp_path / "kamiwaza-extensions-graphiti"
    uat_dir = repo / ".uat"
    uat_dir.mkdir(parents=True)

    (uat_dir / "plan.md").write_text("# Plan\nstep1", encoding="utf-8")
    (uat_dir / "flows.yaml").write_text("flows: []", encoding="utf-8")
    (uat_dir / "ignore.bin").write_bytes(b"\x01\x02")

    settings = _settings(str(tmp_path / "kamiwaza-extensions-*"), max_files=1, max_chars=5)
    loader = UATContextLoader(settings)

    bundle = loader.load_bundle(component="graphiti")
    assert bundle.component == "graphiti"
    assert len(bundle.source_dirs) == 1
    assert len(bundle.docs) == 1
    assert bundle.docs[0].path.endswith(("flows.yaml", "plan.md"))
    assert len(bundle.docs[0].content) == 5
