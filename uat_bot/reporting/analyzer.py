"""AI-powered screenshot analysis for UAT run reports.

Uses claude/codex CLI (same pattern as the scenario builder) to read
screenshots and produce structured pass/fail verdicts per step.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Max screenshots per CLI call (keep prompt manageable)
_BATCH_SIZE = 8
# Max total screenshots to analyze (cost/time guard)
_MAX_SCREENSHOTS = 60


@dataclass
class StepVerdict:
    """AI verdict for a single screenshot / step."""

    screenshot: str  # relative path
    verdict: str  # "pass", "fail", "warn"
    summary: str  # one-line description
    issues: list[str] = field(default_factory=list)


@dataclass
class AnalysisReport:
    """Full AI analysis of a UAT run."""

    overall_verdict: str  # "pass", "fail", "warn"
    executive_summary: str
    step_verdicts: list[StepVerdict] = field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    warn_count: int = 0
    error: str | None = None  # set if analysis itself failed


_BATCH_PROMPT = """\
You are a senior QA engineer reviewing screenshots from an automated UAT \
(User Acceptance Testing) run on the Kamiwaza AI platform.

I need you to read the following screenshot image files and analyze each one. \
Use the Read tool to view each image file listed below.

SCREENSHOT FILES TO ANALYZE:
{screenshot_list}

For each screenshot, determine:
1. **Verdict**: "pass" (page looks correct), "fail" (clear error or broken \
state), or "warn" (suspicious but not definitively broken)
2. **Summary**: One sentence describing what the page shows
3. **Issues**: List any specific problems (empty list if pass)

Look for:
- Error messages, red banners, toast notifications, HTTP error codes
- Broken layouts, overlapping elements, missing images
- Loading spinners that appear stuck
- Empty states where content should exist
- Login failures, "Session Expired", 401/403/500 pages
- Garbled text or untranslated i18n keys

Here is context from the test metrics (action log):
{metrics_context}

Respond with ONLY a JSON array. Each element must match:
{{"screenshot": "<filename>", "verdict": "pass"|"fail"|"warn", \
"summary": "<description>", "issues": ["<issue1>", ...]}}

Output ONLY the JSON array, no markdown fences, no explanation."""

_SUMMARY_PROMPT = """\
You are a senior QA engineer writing an executive summary for a UAT run.

Here are the per-screenshot verdicts from the analysis:
{verdicts_json}

Write a concise executive summary (3-6 sentences) covering:
1. Overall result: did the test run pass, fail, or have warnings?
2. Key findings: what worked, what broke?
3. Patterns: any recurring issues across steps?
4. Recommendation: is the build ready for release?

Also provide an overall verdict: "pass", "fail", or "warn".

Respond with ONLY a JSON object:
{{"overall_verdict": "pass"|"fail"|"warn", "executive_summary": "<summary>"}}

Output ONLY the JSON object, no markdown fences, no explanation."""


def _detect_backend() -> str | None:
    """Return the best available LLM CLI backend, or None."""
    if shutil.which("claude"):
        return "claude"
    if shutil.which("codex") and os.environ.get("OPENAI_API_KEY"):
        return "codex"
    return None


class RunAnalyzer:
    """Analyzes a completed UAT run's screenshots using claude/codex CLI."""

    def __init__(
        self,
        backend: str | None = None,
        max_screenshots: int = _MAX_SCREENSHOTS,
    ) -> None:
        self.backend = backend or _detect_backend()
        self.max_screenshots = max_screenshots

    async def analyze_run(self, run_dir: Path) -> AnalysisReport:
        """Analyze all screenshots from a run directory.

        Args:
            run_dir: Path to the run directory containing screenshots/ and metrics.jsonl.

        Returns:
            AnalysisReport with per-step verdicts and executive summary.
        """
        if not self.backend:
            return AnalysisReport(
                overall_verdict="warn",
                executive_summary=(
                    "AI analysis skipped: no LLM backend available. "
                    "Install claude CLI or codex CLI (with OPENAI_API_KEY)."
                ),
                error="no_backend",
            )

        try:
            return await self._do_analysis(run_dir)
        except Exception as exc:
            logger.exception("AI analysis failed for %s", run_dir)
            return AnalysisReport(
                overall_verdict="warn",
                executive_summary=f"AI analysis could not be completed: {exc}",
                error=str(exc),
            )

    async def _do_analysis(self, run_dir: Path) -> AnalysisReport:
        # Collect screenshots
        shots_dir = run_dir / "screenshots"
        screenshot_paths: list[Path] = []
        if shots_dir.exists():
            screenshot_paths = sorted(shots_dir.rglob("*.png")) + sorted(
                shots_dir.rglob("*.jpg")
            )

        if not screenshot_paths:
            return AnalysisReport(
                overall_verdict="warn",
                executive_summary="No screenshots found to analyze.",
            )

        # Cap at max to control costs
        if len(screenshot_paths) > self.max_screenshots:
            step = len(screenshot_paths) / self.max_screenshots
            screenshot_paths = [
                screenshot_paths[int(i * step)]
                for i in range(self.max_screenshots)
            ]

        # Load metrics for context
        metrics_context = _load_metrics_context(run_dir)

        # Analyze in batches
        all_verdicts: list[StepVerdict] = []
        for i in range(0, len(screenshot_paths), _BATCH_SIZE):
            batch = screenshot_paths[i : i + _BATCH_SIZE]
            batch_verdicts = await self._analyze_batch(
                batch, run_dir, metrics_context
            )
            all_verdicts.extend(batch_verdicts)

        # Count results
        pass_count = sum(1 for v in all_verdicts if v.verdict == "pass")
        fail_count = sum(1 for v in all_verdicts if v.verdict == "fail")
        warn_count = sum(1 for v in all_verdicts if v.verdict == "warn")

        # Generate executive summary
        overall_verdict, executive_summary = await self._generate_summary(
            all_verdicts
        )

        return AnalysisReport(
            overall_verdict=overall_verdict,
            executive_summary=executive_summary,
            step_verdicts=all_verdicts,
            pass_count=pass_count,
            fail_count=fail_count,
            warn_count=warn_count,
        )

    async def _analyze_batch(
        self,
        screenshot_paths: list[Path],
        run_dir: Path,
        metrics_context: str,
    ) -> list[StepVerdict]:
        """Send a batch of screenshots to the LLM CLI for analysis."""
        screenshot_list = "\n".join(
            f"- {path}" for path in screenshot_paths
        )

        prompt = _BATCH_PROMPT.format(
            screenshot_list=screenshot_list,
            metrics_context=metrics_context,
        )

        raw = await _call_llm_cli(self.backend, prompt)
        verdicts = _parse_verdicts(raw, screenshot_paths, run_dir)
        return verdicts

    async def _generate_summary(
        self, verdicts: list[StepVerdict]
    ) -> tuple[str, str]:
        """Generate executive summary from all verdicts."""
        verdicts_json = json.dumps(
            [
                {
                    "screenshot": v.screenshot,
                    "verdict": v.verdict,
                    "summary": v.summary,
                    "issues": v.issues,
                }
                for v in verdicts
            ],
            indent=2,
        )

        prompt = _SUMMARY_PROMPT.format(verdicts_json=verdicts_json)
        raw = await _call_llm_cli(self.backend, prompt)

        parsed = _extract_json(raw)
        return (
            parsed.get("overall_verdict", "warn"),
            parsed.get("executive_summary", "Summary generation failed."),
        )


async def _call_llm_cli(backend: str | None, prompt: str) -> str:
    """Call an LLM CLI backend with a text prompt.

    Same pattern as uat_bot.scenarios.explorer._call_llm_cli.
    """
    if not backend:
        return ""

    try:
        if backend == "claude":
            proc = await asyncio.to_thread(
                subprocess.run,
                [
                    "claude", "-p", prompt,
                    "--output-format", "text",
                    "--allowedTools", "Read",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
        else:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["codex", "exec", "--full-auto", prompt],
                capture_output=True,
                text=True,
                timeout=180,
            )
        if proc.returncode != 0:
            logger.warning(
                "LLM CLI failed (rc=%d): %s",
                proc.returncode,
                proc.stderr[:300],
            )
            return ""
        return proc.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("LLM CLI timed out for analysis batch")
        return ""
    except FileNotFoundError:
        logger.warning("%s CLI not found in PATH", backend)
        return ""


def _load_metrics_context(run_dir: Path) -> str:
    """Load metrics.jsonl and format as context for the prompt."""
    metrics_path = run_dir / "metrics.jsonl"
    if not metrics_path.exists():
        return "(No metrics available)"

    rows: list[dict] = []
    for line in metrics_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not rows:
        return "(No metrics recorded)"

    lines = []
    for row in rows[:40]:
        action = row.get("action", "?")
        status = row.get("status", "?")
        detail = row.get("detail", "")
        worker = row.get("worker_id", "?")
        line = f"[{worker}] {action}: {status}"
        if detail:
            line += f" — {detail[:120]}"
        lines.append(line)
    if len(rows) > 40:
        lines.append(f"... and {len(rows) - 40} more actions")
    return "\n".join(lines)


def _parse_verdicts(
    text: str, paths: list[Path], run_dir: Path
) -> list[StepVerdict]:
    """Parse the LLM's JSON array response into StepVerdict objects."""
    parsed = _extract_json_array(text)

    # Build lookup by filename for matching
    path_map: dict[str, str] = {}
    for p in paths:
        rel = p.relative_to(run_dir).as_posix()
        path_map[p.name] = rel
        path_map[rel] = rel
        path_map[str(p)] = rel

    verdicts: list[StepVerdict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        screenshot = item.get("screenshot", "")
        # Resolve to our known relative path
        resolved = (
            path_map.get(screenshot)
            or path_map.get(screenshot.split("/")[-1])
            or screenshot
        )
        verdicts.append(
            StepVerdict(
                screenshot=resolved,
                verdict=item.get("verdict", "warn"),
                summary=item.get("summary", ""),
                issues=item.get("issues", []),
            )
        )

    # Fill in any screenshots that weren't in the response
    covered = {v.screenshot for v in verdicts}
    for p in paths:
        rel = p.relative_to(run_dir).as_posix()
        if rel not in covered:
            verdicts.append(
                StepVerdict(
                    screenshot=rel,
                    verdict="warn",
                    summary="Not analyzed (missing from AI response)",
                )
            )

    return verdicts


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return {}


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from LLM response."""
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []
