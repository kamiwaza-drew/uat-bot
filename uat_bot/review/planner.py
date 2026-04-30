from __future__ import annotations

from dataclasses import dataclass

from uat_bot.models import ReviewPlan, ReviewRunRequest, RunCreateRequest
from uat_bot.scenarios.loader import load_all_scenarios


@dataclass(frozen=True)
class ReviewRule:
    name: str
    focus: str
    scenarios: tuple[str, ...]
    keywords: tuple[str, ...]
    component: str | None = None


_RULES: tuple[ReviewRule, ...] = (
    ReviewRule(
        name="kaizen_chat",
        focus="chat and agent interaction",
        scenarios=("kaizen_chat",),
        keywords=("kaizen", "chat", "conversation", "agent", "prompt", "message"),
        component="kaizen",
    ),
    ReviewRule(
        name="access_control",
        focus="authentication and access control",
        scenarios=("login", "rbac_boundary", "cluster_admin"),
        keywords=("auth", "login", "rbac", "role", "permission", "admin", "user"),
    ),
    ReviewRule(
        name="settings",
        focus="settings and preferences flows",
        scenarios=("settings",),
        keywords=("settings", "preferences", "profile", "account"),
    ),
    ReviewRule(
        name="model_management",
        focus="model browsing and deployment flows",
        scenarios=("model_browse", "model_deploy"),
        keywords=("model", "models", "deploy", "inference"),
    ),
    ReviewRule(
        name="app_deployment",
        focus="app garden and deployment flows",
        scenarios=("app_garden", "app_deploy"),
        keywords=("app garden", "template", "extension", "app", "catalog"),
    ),
    ReviewRule(
        name="vector_data",
        focus="vector database and retrieval flows",
        scenarios=("vectordb",),
        keywords=("vector", "vectordb", "milvus", "vespa", "graphiti", "retrieval"),
        component="graphiti",
    ),
    ReviewRule(
        name="workrooms",
        focus="workroom management flows",
        scenarios=("workroom",),
        keywords=("workroom", "workspace", "tenant"),
    ),
)

_ROLE_LEVEL = {"viewer": 1, "editor": 2, "admin": 3, "user": 2}


class ReviewPlanner:
    def __init__(self) -> None:
        self._scenario_catalog = load_all_scenarios()

    def build_plan(self, request: ReviewRunRequest) -> ReviewPlan:
        text_parts = list(request.changed_files)
        text_parts.extend(
            part for part in (request.pr_title, request.pr_body, request.component_override) if part
        )
        haystack = "\n".join(text_parts).lower()

        scored_rules: list[tuple[int, ReviewRule]] = []
        for rule in _RULES:
            score = sum(1 for keyword in rule.keywords if keyword in haystack)
            if score > 0:
                scored_rules.append((score, rule))
        scored_rules.sort(key=lambda item: (-item[0], item[1].name))

        selected_scenarios: list[str] = []
        rationale: list[str] = []
        matched_rules: list[str] = []
        review_focus_parts: list[str] = []

        for scenario_name in request.preferred_scenarios:
            if scenario_name in self._scenario_catalog and scenario_name not in selected_scenarios:
                selected_scenarios.append(scenario_name)
                rationale.append(f"Preferred scenario '{scenario_name}' was supplied explicitly.")

        top_component: str | None = request.component_override
        for score, rule in scored_rules:
            matched_rules.append(rule.name)
            review_focus_parts.append(rule.focus)
            if top_component is None and rule.component:
                top_component = rule.component
            rationale.append(
                f"Matched review rule '{rule.name}' from changed-file and PR text signals (score {score})."
            )
            for scenario_name in rule.scenarios[:2]:
                if scenario_name in self._scenario_catalog and scenario_name not in selected_scenarios:
                    selected_scenarios.append(scenario_name)
                if len(selected_scenarios) >= request.max_scenarios:
                    break
            if len(selected_scenarios) >= request.max_scenarios:
                break

        if not selected_scenarios:
            selected_scenarios = ["login", "settings"]
            rationale.append("No direct scenario mapping matched; falling back to login plus settings smoke coverage.")

        selected_scenarios = selected_scenarios[: request.max_scenarios]
        scenario_weights = {
            scenario_name: max(1, len(selected_scenarios) - idx)
            for idx, scenario_name in enumerate(selected_scenarios)
        }
        review_focus = ", ".join(dict.fromkeys(review_focus_parts)) or "general smoke coverage"
        required_role = self._required_role_for(selected_scenarios)

        return ReviewPlan(
            component=top_component,
            review_focus=review_focus,
            scenarios=selected_scenarios,
            scenario_weights=scenario_weights,
            rationale=rationale,
            matched_rules=matched_rules,
            required_role=required_role,
            changed_files_count=len(request.changed_files),
        )

    def build_run_request(self, request: ReviewRunRequest, plan: ReviewPlan) -> RunCreateRequest:
        role = plan.required_role if plan.required_role in {"viewer", "editor", "admin"} else "viewer"
        duration = max(90, 75 * len(plan.scenarios))

        return RunCreateRequest(
            concurrent_users=1,
            role_distribution={role: 1},
            browser_distribution={"chromium": 1},
            os_emulation=["win-chrome"],
            scenarios=plan.scenarios,
            scenario_weights=plan.scenario_weights,
            component=plan.component,
            kamiwaza_url=request.target_url,
            kamiwaza_admin_user=request.username,
            kamiwaza_admin_password=request.password,
            extension_url=request.target_url,
            skip_user_provisioning=True,
            single_iteration=True,
            duration_seconds=duration,
            ramp_up_seconds=0,
            vision_enabled=request.vision_enabled,
            exploratory_pct=0.0,
            test_message=request.test_message or request.pr_title or "Review the current experience and note regressions.",
        )

    def _required_role_for(self, scenario_names: list[str]) -> str:
        best_role = "viewer"
        best_level = _ROLE_LEVEL[best_role]
        for scenario_name in scenario_names:
            scenario = self._scenario_catalog.get(scenario_name)
            if scenario is None:
                continue
            level = _ROLE_LEVEL.get(scenario.required_role, 1)
            if level > best_level:
                best_level = level
                best_role = scenario.required_role
        return best_role
