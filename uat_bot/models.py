from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RunStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"
    cancelled = "CANCELLED"


class ReviewTriggerType(str, Enum):
    local = "LOCAL"
    github = "GITHUB"
    manual = "MANUAL"


class RunCreateRequest(BaseModel):
    concurrent_users: int = Field(ge=1, le=200)
    role_distribution: dict[str, int]
    browser_distribution: dict[str, int]
    os_emulation: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=lambda: ["login"])
    scenario_weights: dict[str, int] = Field(default_factory=dict)
    component: str | None = None
    kamiwaza_url: str | None = None
    kamiwaza_admin_user: str | None = None
    kamiwaza_admin_password: str | None = None
    kamiwaza_admin_token: str | None = None
    extension_url: str | None = None
    skip_user_provisioning: bool = False
    single_iteration: bool = False
    duration_seconds: int = Field(default=120, ge=10, le=86_400)
    ramp_up_seconds: int = Field(default=0, ge=0, le=3_600)
    vision_enabled: bool = False
    exploratory_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    test_message: str | None = None

    @model_validator(mode="after")
    def validate_distributions(self) -> "RunCreateRequest":
        role_total = sum(self.role_distribution.values())
        browser_total = sum(self.browser_distribution.values())
        if role_total != self.concurrent_users:
            raise ValueError(
                f"role_distribution totals {role_total}, expected {self.concurrent_users} concurrent_users"
            )
        if browser_total != self.concurrent_users:
            raise ValueError(
                f"browser_distribution totals {browser_total}, expected {self.concurrent_users} concurrent_users"
            )
        return self


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    test_type: str = "kamiwaza"
    trigger_type: str = "manual"
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    concurrent_users: int
    completed_workers: int = 0
    failed_workers: int = 0
    review_focus: str | None = None
    review_verdict: str | None = None
    changed_files_count: int = 0


class RunDetail(RunSummary):
    progress_pct: float = 0.0
    errors: list[str] = Field(default_factory=list)
    metrics_path: str | None = None
    event_log_path: str | None = None
    report_path: str | None = None
    users_created: int = 0
    component: str | None = None
    uat_guidance_files: list[str] = Field(default_factory=list)
    effective_kamiwaza_url: str | None = None
    auth_source: str | None = None
    review_request: dict[str, Any] | None = None
    review_plan: dict[str, Any] | None = None
    review_summary: dict[str, Any] | None = None


class ReviewRunRequest(BaseModel):
    trigger_type: ReviewTriggerType = ReviewTriggerType.local
    target_url: str
    changed_files: list[str] = Field(default_factory=list)
    pr_title: str | None = None
    pr_body: str | None = None
    repository: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    actor: str | None = None
    username: str = "admin"
    password: str | None = None
    component_override: str | None = None
    preferred_scenarios: list[str] = Field(default_factory=list)
    vision_enabled: bool = True
    max_scenarios: int = Field(default=3, ge=1, le=6)
    test_message: str | None = None

    @model_validator(mode="after")
    def normalize_inputs(self) -> "ReviewRunRequest":
        self.changed_files = list(dict.fromkeys(x.strip() for x in self.changed_files if x and x.strip()))
        self.preferred_scenarios = list(
            dict.fromkeys(x.strip() for x in self.preferred_scenarios if x and x.strip())
        )
        self.username = self.username.strip() or "admin"
        self.password = self.password.strip() if self.password else None
        return self


class ReviewPlan(BaseModel):
    component: str | None = None
    review_focus: str
    scenarios: list[str] = Field(default_factory=list)
    scenario_weights: dict[str, int] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    required_role: str = "viewer"
    changed_files_count: int = 0


class ReviewFinding(BaseModel):
    severity: str
    summary: str
    details: list[str] = Field(default_factory=list)
    screenshot: str | None = None


class ReviewSummary(BaseModel):
    trigger_type: ReviewTriggerType = ReviewTriggerType.local
    verdict: str
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    review_focus: str | None = None
    component: str | None = None
    scenario_names: list[str] = Field(default_factory=list)
    changed_files_count: int = 0
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    comment_markdown: str = ""
    generated_at: datetime | None = None


class UATGuidanceDoc(BaseModel):
    path: str
    content: str


class UATGuidanceBundle(BaseModel):
    component: str | None = None
    source_dirs: list[str] = Field(default_factory=list)
    docs: list[UATGuidanceDoc] = Field(default_factory=list)

    @property
    def file_paths(self) -> list[str]:
        return [doc.path for doc in self.docs]

    def combined_context(self, max_chars: int = 10_000) -> str:
        if not self.docs:
            return ""
        joined = "\n\n".join(f"[{doc.path}]\n{doc.content}" for doc in self.docs)
        return joined[:max_chars]


class RunEvent(BaseModel):
    ts: datetime
    run_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class TestUser(BaseModel):
    __test__ = False

    username: str
    password: str
    role: str
    user_id: str


class WorkerAssignment(BaseModel):
    worker_id: str
    user: TestUser
    browser: str
    os_profile: str
    scenarios: list[str]


class ScenarioGenerateRequest(BaseModel):
    prompt: str
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    backend: str | None = None


class ScenarioGenerateResponse(BaseModel):
    yaml_content: str
    name: str
    errors: list[str] = Field(default_factory=list)
    backend_used: str


class ScenarioSaveRequest(BaseModel):
    name: str
    yaml_content: str


class ScenarioSaveResponse(BaseModel):
    saved: bool
    path: str | None = None
    errors: list[str] = Field(default_factory=list)
