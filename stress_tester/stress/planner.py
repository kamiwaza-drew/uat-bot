from __future__ import annotations

from itertools import cycle

from stress_tester.models import TestUser, WorkerAssignment


class AssignmentPlanner:
    @staticmethod
    def _expand_distribution(distribution: dict[str, int]) -> list[str]:
        items: list[str] = []
        for key, count in distribution.items():
            items.extend([key] * max(0, count))
        return items

    def assign(
        self,
        users: list[TestUser],
        browser_distribution: dict[str, int],
        os_profiles: list[str],
        scenarios: list[str],
    ) -> list[WorkerAssignment]:
        browsers = self._expand_distribution(browser_distribution)
        if len(browsers) != len(users):
            raise ValueError(
                f"browser_distribution count ({len(browsers)}) does not match users ({len(users)})"
            )

        profile_list = os_profiles or ["win-chrome"]
        profile_cycle = cycle(profile_list)

        assignments: list[WorkerAssignment] = []
        for idx, user in enumerate(users):
            assignments.append(
                WorkerAssignment(
                    worker_id=f"worker-{idx + 1:03d}",
                    user=user,
                    browser=browsers[idx],
                    os_profile=next(profile_cycle),
                    scenarios=scenarios or ["login"],
                )
            )
        return assignments
