from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PageValidation(BaseModel):
    matches_expected: bool
    errors_detected: list[str]
    loading_visible: bool
    layout_issues: list[str]
    confidence: float
    page_description: str


class ExploratoryAction(BaseModel):
    action_type: Literal["click", "navigate", "fill", "scroll", "report_bug"]
    target: str
    value: str | None = None
    reasoning: str


class CrossBrowserDiff(BaseModel):
    has_meaningful_differences: bool
    differences: list[str]
    severity: Literal["none", "cosmetic", "functional", "broken"]


class BugReport(BaseModel):
    title: str
    description: str
    severity: Literal["critical", "major", "minor", "cosmetic"]
    reproduction_steps: list[str]
    affected_browsers: list[str]
    screenshot_refs: list[str]
