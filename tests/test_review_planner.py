from __future__ import annotations

from stress_tester.models import ReviewRunRequest
from stress_tester.review.planner import ReviewPlanner


def test_review_planner_matches_kaizen_chat_signals():
    planner = ReviewPlanner()

    request = ReviewRunRequest(
        target_url="https://preview.example.test/runtime/apps/kaizen/",
        changed_files=[
            "apps/kaizen/src/components/ChatComposer.tsx",
            "apps/kaizen/src/routes/conversations/[id].tsx",
        ],
        pr_title="Improve chat composer and conversation rendering",
    )

    plan = planner.build_plan(request)

    assert plan.component == "kaizen"
    assert "kaizen_chat" in plan.scenarios
    assert "chat and agent interaction" in plan.review_focus


def test_review_planner_falls_back_to_smoke_scenarios():
    planner = ReviewPlanner()

    request = ReviewRunRequest(
        target_url="https://preview.example.test",
        changed_files=["docs/notes.md"],
        pr_title="Refresh documentation",
    )

    plan = planner.build_plan(request)

    assert plan.scenarios == ["login", "settings"]
    assert plan.required_role == "viewer"
    assert plan.changed_files_count == 1
