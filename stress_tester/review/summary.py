from __future__ import annotations

from datetime import UTC, datetime

from stress_tester.models import ReviewFinding, ReviewPlan, ReviewRunRequest, ReviewSummary
from stress_tester.reporting.analyzer import AnalysisReport


def build_review_summary(
    *,
    run_id: str,
    request: ReviewRunRequest,
    plan: ReviewPlan,
    ai_analysis: AnalysisReport | None,
    state_errors: list[str],
) -> ReviewSummary:
    findings: list[ReviewFinding] = []

    if ai_analysis:
        for verdict in ai_analysis.step_verdicts:
            if verdict.verdict not in {"fail", "warn"}:
                continue
            findings.append(
                ReviewFinding(
                    severity=verdict.verdict,
                    summary=verdict.summary,
                    details=verdict.issues,
                    screenshot=verdict.screenshot,
                )
            )
            if len(findings) >= 5:
                break

    for err in state_errors[:3]:
        findings.append(
            ReviewFinding(
                severity="fail",
                summary="Runtime error occurred during review run.",
                details=[err],
            )
        )

    verdict = "pass"
    if any(item.severity == "fail" for item in findings):
        verdict = "fail"
    elif findings:
        verdict = "warn"
    elif ai_analysis and ai_analysis.overall_verdict in {"fail", "warn"}:
        verdict = ai_analysis.overall_verdict

    if ai_analysis and ai_analysis.executive_summary:
        summary_text = ai_analysis.executive_summary
    elif verdict == "pass":
        summary_text = "Review run completed without model-identified regressions or runtime errors."
    else:
        summary_text = "Review run completed with issues that should be inspected before merge."

    artifact_paths = {
        "report": "report.html",
    }
    if ai_analysis and not ai_analysis.error:
        artifact_paths["analysis"] = "ai_analysis.json"

    comment_lines = [
        f"## UAT Review Verdict: {verdict.upper()}",
        "",
        f"- Focus: {plan.review_focus}",
        f"- Scenarios: {', '.join(plan.scenarios)}",
        f"- Changed files: {plan.changed_files_count}",
        f"- Report: `/runs/{run_id}/report`",
        "",
        summary_text,
    ]
    if findings:
        comment_lines.extend(["", "### Findings"])
        for item in findings[:5]:
            details = f" ({'; '.join(item.details[:2])})" if item.details else ""
            comment_lines.append(f"- [{item.severity}] {item.summary}{details}")

    return ReviewSummary(
        trigger_type=request.trigger_type,
        verdict=verdict,
        summary=summary_text,
        findings=findings,
        review_focus=plan.review_focus,
        component=plan.component,
        scenario_names=plan.scenarios,
        changed_files_count=plan.changed_files_count,
        artifact_paths=artifact_paths,
        comment_markdown="\n".join(comment_lines).strip(),
        generated_at=datetime.now(UTC),
    )
