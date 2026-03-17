from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import glob
from typing import TYPE_CHECKING

from uat_bot.models import UATGuidanceBundle, UATGuidanceDoc

if TYPE_CHECKING:
    from uat_bot.config import Settings

ALLOWED_SUFFIXES = {".md", ".markdown", ".yaml", ".yml", ".json", ".txt"}


@dataclass(slots=True)
class UATContextLoader:
    settings: Settings

    def _repo_roots(self) -> list[Path]:
        roots: list[Path] = []
        patterns = [x.strip() for x in self.settings.uat_extension_roots.split(",") if x.strip()]
        for pattern in patterns:
            matches = [Path(p) for p in glob.glob(pattern)]
            if matches:
                roots.extend(matches)
                continue
            fallback = Path(pattern)
            if fallback.exists():
                roots.append(fallback)

        unique: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            resolved = root.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(resolved)
        return sorted(unique)

    def discover_uat_dirs(self, component: str | None = None) -> list[Path]:
        uat_dirs: list[Path] = []
        for root in self._repo_roots():
            if not root.exists() or not root.is_dir():
                continue
            candidate = root / ".uat"
            if candidate.exists() and candidate.is_dir():
                if component and component.lower() not in root.name.lower():
                    continue
                uat_dirs.append(candidate.resolve())

        return sorted(uat_dirs)

    def load_bundle(self, component: str | None = None) -> UATGuidanceBundle:
        docs: list[UATGuidanceDoc] = []
        source_dirs: list[str] = []

        for uat_dir in self.discover_uat_dirs(component=component):
            source_dirs.append(str(uat_dir))
            files = sorted(uat_dir.rglob("*"))
            for file_path in files:
                if len(docs) >= self.settings.uat_guidance_max_files:
                    break
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                trimmed = text.strip()
                if not trimmed:
                    continue
                docs.append(
                    UATGuidanceDoc(
                        path=str(file_path),
                        content=trimmed[: self.settings.uat_guidance_max_chars_per_file],
                    )
                )

        return UATGuidanceBundle(component=component, source_dirs=source_dirs, docs=docs)
