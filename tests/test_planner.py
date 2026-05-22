from __future__ import annotations

from stress_tester.models import TestUser
from stress_tester.stress.planner import AssignmentPlanner


def test_assignment_planner_generates_expected_assignments():
    users = [
        TestUser(username="u1", password="p", role="admin", user_id="1"),
        TestUser(username="u2", password="p", role="editor", user_id="2"),
        TestUser(username="u3", password="p", role="viewer", user_id="3"),
    ]
    planner = AssignmentPlanner()

    assignments = planner.assign(
        users=users,
        browser_distribution={"chromium": 2, "firefox": 1},
        os_profiles=["win-chrome", "mac-firefox"],
        scenarios=["login"],
    )

    assert len(assignments) == 3
    assert assignments[0].browser == "chromium"
    assert assignments[2].browser == "firefox"
    assert assignments[1].os_profile in {"win-chrome", "mac-firefox"}
