# Stress Tester Plan: Containerized Vision-Guided Stress Testing

## Overview

A standalone containerized application that stress-tests the Kamiwaza platform by simulating many concurrent users across different browsers and OS fingerprints. Uses Playwright for browser automation, captures screenshots at every step, and feeds them to a vision-capable LLM (Claude) to validate UI state, detect bugs, and drive exploratory testing.

**This is NOT a test suite embedded in the main repo** — it's a self-contained Docker image with a FastAPI control plane, deployable via the Kamiwaza App Garden or standalone `docker compose`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Stress Tester Container                           │
│                                                                 │
│  ┌────────────────┐   ┌────────────────────────────────────┐   │
│  │ Control Plane   │   │        Worker Pool                 │   │
│  │ (FastAPI)       │   │                                    │   │
│  │                 │   │  ┌──────────┐  ┌──────────┐       │   │
│  │ POST /runs      │──▶│  │ Worker 1  │  │ Worker 2  │  ... │   │
│  │ GET  /runs/:id  │   │  │ Alice     │  │ Bob       │       │   │
│  │ GET  /report    │   │  │ Chrome/Win│  │ FF/macOS  │       │   │
│  │ WS   /live      │   │  │ admin     │  │ viewer    │       │   │
│  └───────┬────────┘   │  └─────┬────┘  └─────┬────┘       │   │
│          │             │        │              │             │   │
│          │             └────────┼──────────────┼─────────────┘   │
│          │                      │              │                 │
│  ┌───────▼──────────────────────▼──────────────▼───────────┐   │
│  │                    Vision LLM Client                     │   │
│  │              (Anthropic API — Claude Sonnet)              │   │
│  └───────┬─────────────────────────────────────────────────┘   │
│          │                                                      │
│  ┌───────▼──────────────────────────────────────────────────┐  │
│  │                   Results Store                           │  │
│  │  /data/runs/{run_id}/                                     │  │
│  │    ├── screenshots/  (per-user, per-step PNGs)            │  │
│  │    ├── har/          (network captures)                   │  │
│  │    ├── analysis/     (LLM responses as JSON)              │  │
│  │    ├── metrics.jsonl (timing, errors)                     │  │
│  │    └── report.html   (rendered gallery + timeline)        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
          │
          │  Targets
          ▼
┌──────────────────┐
│  Kamiwaza App    │
│  (https://...)   │
│                  │
│  - Creates users │
│  - Runs flows    │
│  - Takes shots   │
│  - Reports bugs  │
└──────────────────┘
```

---

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Packaging | Standalone Docker image | Decoupled from main repo lifecycle; deployable anywhere |
| Control plane | FastAPI inside container | Start/stop runs via API; integrate with CI or App Garden |
| Browser engine | Playwright (Python, all 3 engines) | Chromium, Firefox, WebKit in one container; OS emulation via device descriptors |
| User simulation | Real Kamiwaza accounts created via Admin API | Tests actual auth flow, RBAC, workroom isolation |
| Vision LLM | Claude API (Sonnet for speed, Opus for ambiguity) | Native vision, structured output, tool use |
| Result storage | Volume-mounted `/data` | Survives container restarts; hostPath or PVC in K8s |
| Report format | Self-contained HTML with embedded screenshots | Single file to share; no web server needed to view |

---

## Directory Structure (inside container)

```
/app/
├── Dockerfile
├── docker-compose.yml          # For standalone deployment
├── pyproject.toml
├── stress_tester/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + entrypoint
│   ├── config.py               # Pydantic Settings from env vars
│   ├── api/
│   │   ├── __init__.py
│   │   ├── runs.py             # POST /runs, GET /runs/:id, DELETE /runs/:id
│   │   ├── reports.py          # GET /report/:run_id (HTML), GET /screenshots/:path
│   │   └── live.py             # WebSocket /live/:run_id (real-time progress)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # Manages run lifecycle, spawns workers
│   │   ├── worker.py           # Single user session: browser + scenario + vision
│   │   ├── user_manager.py     # Create/delete test users via Kamiwaza Admin API
│   │   └── run_state.py        # Run state machine (PENDING → RUNNING → COMPLETE/FAILED)
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── profiles.py         # OS/browser/viewport combinations
│   │   ├── actions.py          # Playwright action primitives (click, fill, nav, wait)
│   │   └── screenshots.py      # Screenshot capture, naming, storage
│   ├── vision/
│   │   ├── __init__.py
│   │   ├── client.py           # Anthropic API wrapper
│   │   ├── prompts.py          # Vision prompt templates
│   │   └── schemas.py          # Pydantic models for LLM responses
│   ├── scenarios/
│   │   ├── __init__.py
│   │   ├── loader.py           # YAML scenario parser
│   │   ├── builtin/            # Shipped scenario YAMLs
│   │   │   ├── login.yaml
│   │   │   ├── model_browse.yaml
│   │   │   ├── model_deploy.yaml
│   │   │   ├── app_garden.yaml
│   │   │   ├── cluster_admin.yaml
│   │   │   ├── vectordb.yaml
│   │   │   ├── workroom.yaml
│   │   │   └── exploratory.yaml
│   │   └── custom/             # Volume-mountable for user-authored scenarios
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── generator.py        # HTML report builder
│   │   ├── templates/          # Jinja2 HTML templates
│   │   │   └── report.html.j2
│   │   └── metrics.py          # Timing aggregation, error categorization
│   └── stress/
│       ├── __init__.py
│       ├── planner.py          # Weighted scenario distribution across users
│       └── ramp.py             # Ramp-up/ramp-down scheduling
├── tests/                      # Unit tests for the bot itself
│   ├── test_orchestrator.py
│   ├── test_user_manager.py
│   ├── test_vision_client.py
│   └── test_scenario_loader.py
└── data/                       # Volume mount point for results
    └── runs/
```

---

## Phase 1: Container Shell + User Management

### 1.1 Container setup
- `Dockerfile` based on `mcr.microsoft.com/playwright/python:v1.50.0-noble`
  - Playwright browsers pre-installed (Chromium, Firefox, WebKit)
  - Python 3.12, uv for deps
  - Non-root user `uat`
- `docker-compose.yml` for standalone usage:
  ```yaml
  services:
    stress-tester:
      build: .
      ports:
        - "18090:18090"
      environment:
        - KAMIWAZA_URL=https://host.docker.internal
        - KAMIWAZA_ADMIN_USER=admin
        - KAMIWAZA_ADMIN_PASSWORD=${KAMIWAZA_ADMIN_PASSWORD}
        - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      volumes:
        - ./data:/data
        - ./scenarios:/app/stress_tester/scenarios/custom
  ```

### 1.2 User manager (`core/user_manager.py`)
- On run start, creates N test users via `POST /api/v1/users/local`:
  ```python
  async def provision_test_users(count: int, role_distribution: dict) -> list[TestUser]:
      """
      Create test users with varied roles.

      role_distribution example:
        {"admin": 1, "editor": 3, "viewer": 6}  # 10 users total

      Returns TestUser objects with username, password, role, user_id.
      """
  ```
- Usernames: `stress-tester-{run_id[:8]}-{role}-{n}` (e.g., `stress-tester-a1b2c3d4-editor-2`)
- On run end, deletes all created users via `DELETE /api/v1/users/{user_id}`
- Cleanup on container start: find and delete any orphaned `stress-tester-*` users from crashed runs

### 1.3 FastAPI control plane (`main.py`, `api/runs.py`)
- `POST /runs` — start a new test run with config:
  ```json
  {
    "concurrent_users": 10,
    "role_distribution": {"admin": 1, "editor": 3, "viewer": 6},
    "browser_distribution": {"chromium": 5, "firefox": 3, "webkit": 2},
    "os_emulation": ["Desktop Chrome Windows", "Desktop Firefox macOS", "Desktop Safari iOS", "Pixel 7"],
    "scenarios": ["login", "model_browse", "model_deploy"],
    "scenario_weights": {"login": 1, "model_browse": 3, "model_deploy": 2},
    "duration_seconds": 600,
    "ramp_up_seconds": 30,
    "vision_enabled": true,
    "exploratory_pct": 0.2
  }
  ```
- `GET /runs/{run_id}` — status, progress, live metrics
- `GET /runs/{run_id}/report` — rendered HTML report
- `DELETE /runs/{run_id}` — stop run, cleanup users
- `GET /runs` — list all runs
- `WS /live/{run_id}` — real-time screenshot feed + progress events

---

## Phase 2: Browser Profiles + Screenshot Pipeline

### 2.1 OS/Browser profiles (`browser/profiles.py`)
Playwright supports device emulation natively. We define profile sets:

```python
PROFILES = {
    # Desktop
    "win-chrome": {
        "browser": "chromium",
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
        "locale": "en-US",
        "timezone_id": "America/New_York",
    },
    "mac-safari": {
        "browser": "webkit",
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 ...",
        "device_scale_factor": 2,  # Retina
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
    },
    "mac-firefox": {
        "browser": "firefox",
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:121.0) Gecko/20100101 ...",
    },
    "linux-chrome": {
        "browser": "chromium",
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ...",
    },
    # Mobile / Tablet
    "iphone-15": playwright.devices["iPhone 15"],
    "pixel-7": playwright.devices["Pixel 7"],
    "ipad-pro": playwright.devices["iPad Pro 11"],
    # Stress-specific
    "slow-3g": {
        "browser": "chromium",
        "viewport": {"width": 1366, "height": 768},
        "offline": False,
        # Network throttling applied separately
    },
}
```

### 2.2 Screenshot pipeline (`browser/screenshots.py`)
- Every Playwright action automatically screenshots before + after
- Naming: `{run_id}/{user_id}/{step:04d}_{action}_{timestamp}.png`
- Configurable resolution (full page vs viewport)
- Optional video recording via Playwright's built-in recorder
- HAR capture enabled per browser context for network analysis

### 2.3 Console + network error capture
- Hook into `page.on("console")` for JS errors/warnings
- Hook into `page.on("pageerror")` for unhandled exceptions
- Hook into `page.on("response")` for HTTP 4xx/5xx
- All captured alongside screenshots in metrics.jsonl

---

## Phase 3: Vision LLM Integration

### 3.1 Vision client (`vision/client.py`)
```python
class VisionClient:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def analyze(
        self,
        screenshot: bytes,
        prompt: str,
        response_schema: type[BaseModel],
        previous_screenshots: list[bytes] | None = None,
    ) -> BaseModel:
        """Send screenshot(s) to Claude and get structured analysis."""
```

### 3.2 Vision prompt catalog (`vision/prompts.py`)
```python
PROMPTS = {
    "page_validation": """
        Look at this screenshot of the Kamiwaza platform.
        Expected state: {expected}

        Answer:
        1. Does the page match the expected state?
        2. Are there any error banners, toasts, or broken elements?
        3. Is there a loading spinner still visible?
        4. Are all text elements readable (not truncated, overlapping)?
        5. Rate confidence 0-1.
    """,

    "error_detection": """
        Examine this screenshot for any signs of problems:
        - Error messages or red banners
        - Broken layouts or overlapping elements
        - Missing images or icons (broken image placeholders)
        - Spinners that appear stuck (compare with previous screenshot)
        - Console error indicators
        - Empty states that shouldn't be empty
        - Garbled or placeholder text
    """,

    "cross_browser_diff": """
        Compare these two screenshots of the same page:
        Screenshot 1: {browser_a} on {os_a}
        Screenshot 2: {browser_b} on {os_b}

        Identify any meaningful rendering differences (not minor anti-aliasing).
        Focus on: layout shifts, missing elements, font issues, broken interactions.
    """,

    "exploratory_next_action": """
        You are testing the Kamiwaza AI platform. You've visited these pages: {history}.

        Current screenshot attached. You are logged in as role: {role}.

        What should you do next to find bugs? Pick ONE action:
        - click(selector_description)
        - navigate(url)
        - fill(selector_description, text)
        - scroll(direction)
        - report_bug(description)

        Prefer areas you haven't explored. Try edge cases.
    """,

    "accessibility_check": """
        Evaluate this screenshot for accessibility issues:
        - Sufficient color contrast
        - Interactive elements are clearly identifiable
        - Text is readable at the viewport size
        - Form fields have visible labels
        - Focus indicators would be visible
    """,
}
```

### 3.3 Structured response schemas (`vision/schemas.py`)
```python
class PageValidation(BaseModel):
    matches_expected: bool
    errors_detected: list[str]
    loading_visible: bool
    layout_issues: list[str]
    confidence: float  # 0-1
    page_description: str

class ExploratoryAction(BaseModel):
    action_type: Literal["click", "navigate", "fill", "scroll", "report_bug"]
    target: str  # selector description or URL
    value: str | None = None  # for fill actions
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
```

---

## Phase 4: Scenario Engine

### 4.1 YAML scenario format
```yaml
name: model_browse_and_deploy
description: Browse models, view details, attempt deployment
timeout: 300
tags: [models, serving, smoke]
required_role: editor  # minimum role needed

steps:
  - action: navigate
    url: /models
    wait_for: networkidle
    validate:
      vision: "The models page is showing a list or grid of AI models"
      no_errors: true

  - action: click
    target: "first model card in the list"  # natural language → LLM resolves selector
    validate:
      vision: "A model detail page is showing with model name, size, and a deploy button"

  - action: click
    target: "deploy button"
    validate:
      vision: "A deployment configuration dialog or page appeared"

  - action: wait_for
    vision: "deployment status shows DEPLOYED, RUNNING, or an error message"
    timeout: 120
    poll_interval: 5

  - action: screenshot
    name: final_deployment_state
    validate:
      vision: "The model is deployed and serving, or there is a clear error explanation"
```

**Key difference from v1 plan**: Selectors are natural language descriptions. The LLM resolves them to actual CSS/XPath selectors by examining the screenshot + page HTML. This makes scenarios resilient to UI changes.

### 4.2 LLM-assisted selector resolution
```python
async def resolve_selector(page, target_description: str, screenshot: bytes) -> str:
    """
    Ask LLM to find the element matching the description.

    1. Send screenshot + page accessibility tree (page.accessibility.snapshot())
    2. LLM returns: CSS selector, role-based locator, or coordinates
    3. Verify element exists via page.locator(selector).count()
    4. Fall back to coordinate-based click if selector fails
    """
```

### 4.3 Built-in scenarios

| Scenario | Role | Browsers | What it stresses |
|----------|------|----------|-----------------|
| `login.yaml` | all | all | Auth flow, Keycloak, cookie handling |
| `model_browse.yaml` | viewer | all | Read paths, pagination, search |
| `model_deploy.yaml` | editor | chromium, firefox | Deploy lifecycle, async status polling |
| `app_garden.yaml` | editor | chromium, webkit | Container deployment, port allocation |
| `cluster_admin.yaml` | admin | chromium | Admin-only routes, RBAC enforcement |
| `vectordb.yaml` | editor | chromium, firefox | Vector DB CRUD |
| `workroom.yaml` | editor | all | Multi-tenant isolation, context switching |
| `rbac_boundary.yaml` | viewer | chromium | Verify viewers CAN'T access admin routes |
| `exploratory.yaml` | all | all | LLM-driven free exploration |

---

## Phase 5: Stress Testing Engine

### 5.1 Orchestrator (`core/orchestrator.py`)
```python
class StressOrchestrator:
    async def run(self, config: RunConfig) -> RunResult:
        # 1. Provision test users
        users = await self.user_manager.provision_test_users(
            count=config.concurrent_users,
            role_distribution=config.role_distribution,
        )

        # 2. Assign browser profiles
        assignments = self.planner.assign(
            users=users,
            browser_distribution=config.browser_distribution,
            os_profiles=config.os_emulation,
            scenario_weights=config.scenario_weights,
        )

        # 3. Ramp up workers
        workers = []
        for i, assignment in enumerate(assignments):
            delay = (config.ramp_up_seconds / len(assignments)) * i
            worker = Worker(
                user=assignment.user,
                profile=assignment.profile,
                scenarios=assignment.scenarios,
                vision_client=self.vision_client,
                results_dir=self.run_dir,
            )
            workers.append(self._launch_with_delay(worker, delay))

        # 4. Run until duration expires or all scenarios complete
        await asyncio.gather(*workers, return_exceptions=True)

        # 5. Generate report
        report = await self.reporter.generate(self.run_dir)

        # 6. Cleanup users
        await self.user_manager.cleanup_test_users(users)

        return RunResult(run_id=self.run_id, report_path=report)
```

### 5.2 Worker (`core/worker.py`)
Each worker is one simulated user with their own:
- Playwright browser context (isolated cookies, storage)
- Browser type + OS emulation profile
- Kamiwaza user account + role
- Scenario queue (weighted random selection)
- Screenshot pipeline
- Vision LLM analysis

```python
class Worker:
    async def run(self):
        async with self._create_browser_context() as context:
            page = await context.new_page()

            # Login as this user
            await self._login(page)

            # Run scenarios until duration expires
            while not self.should_stop():
                scenario = self._pick_next_scenario()
                await self._execute_scenario(page, scenario)

                # Random think time between scenarios (simulate human)
                await asyncio.sleep(random.uniform(2, 10))
```

### 5.3 Stress profiles
Pre-built stress configurations:

```yaml
# stress_profiles/smoke.yaml
name: smoke
concurrent_users: 3
role_distribution: {admin: 1, editor: 1, viewer: 1}
browser_distribution: {chromium: 1, firefox: 1, webkit: 1}
os_emulation: [win-chrome, mac-firefox, mac-safari]
scenarios: [login, model_browse]
duration_seconds: 120
vision_enabled: true

# stress_profiles/load.yaml
name: load
concurrent_users: 20
role_distribution: {admin: 2, editor: 8, viewer: 10}
browser_distribution: {chromium: 10, firefox: 6, webkit: 4}
os_emulation: [win-chrome, mac-safari, mac-firefox, linux-chrome, iphone-15, pixel-7]
scenarios: [login, model_browse, model_deploy, app_garden, workroom]
scenario_weights: {login: 1, model_browse: 4, model_deploy: 2, app_garden: 2, workroom: 1}
duration_seconds: 600
ramp_up_seconds: 60
vision_enabled: true
exploratory_pct: 0.1

# stress_profiles/soak.yaml
name: soak
concurrent_users: 5
role_distribution: {admin: 1, editor: 2, viewer: 2}
browser_distribution: {chromium: 3, firefox: 1, webkit: 1}
scenarios: [login, model_browse, model_deploy, app_garden, cluster_admin, vectordb, workroom]
duration_seconds: 3600  # 1 hour
ramp_up_seconds: 30
vision_enabled: false  # save LLM costs on long runs, screenshot only
```

### 5.4 Cross-browser comparison
After a run with multiple browsers:
1. Identify steps that ran on different browsers for the same scenario
2. Pair up screenshots from matching steps
3. Send pairs to vision LLM for `cross_browser_diff` analysis
4. Flag functional differences (not just cosmetic anti-aliasing)

---

## Phase 6: Reporting

### 6.1 HTML report (`reporting/generator.py`)
Self-contained HTML file with:

**Dashboard section:**
- Run config summary (users, browsers, duration)
- Pass/fail donut chart
- Error category breakdown (visual regression, timeout, HTTP error, JS error, RBAC violation)
- P50/P95/P99 action latencies

**Per-user timeline:**
- Horizontal timeline showing each step
- Thumbnail screenshots (click to enlarge)
- LLM analysis annotations
- Browser/OS badge
- Role badge
- Red highlights on failures

**Cross-browser gallery:**
- Side-by-side screenshots grouped by page
- LLM diff annotations
- Filter by severity

**Bug list:**
- Auto-generated from LLM bug reports
- Grouped by severity
- Screenshot evidence
- Reproduction steps

### 6.2 Metrics export
- `metrics.jsonl` — one JSON object per action:
  ```json
  {
    "ts": "2026-03-17T10:30:00Z",
    "run_id": "abc123",
    "user_id": "stress-tester-a1b2-editor-1",
    "role": "editor",
    "browser": "firefox",
    "os_profile": "mac-firefox",
    "scenario": "model_browse",
    "step": 3,
    "action": "click",
    "target": "model card",
    "duration_ms": 1250,
    "screenshot": "screenshots/editor-1/0003_click_1710670200.png",
    "vision_result": {"matches_expected": true, "confidence": 0.95},
    "http_errors": [],
    "console_errors": []
  }
  ```

### 6.3 Live dashboard (WebSocket)
- Real-time feed of screenshots + status per worker
- Useful for watching a stress run in progress
- Simple web UI served from the container's FastAPI

---

## Phase 7: Exploratory / Autonomous Mode

### 7.1 LLM-driven exploration
- Allocate a percentage of workers to "exploratory" mode
- Instead of following a YAML scenario, the LLM drives:
  1. Screenshot → LLM sees the page
  2. LLM picks an action based on what's unexplored + what might break
  3. Execute action → screenshot → LLM validates result
  4. Repeat for N steps
- LLM maintains a mental map of visited pages and avoids revisiting
- Weighted toward edge cases: empty states, rapid clicking, long text input, special characters

### 7.2 RBAC boundary testing
- Viewers attempt admin actions → should see 403/redirect
- Editors attempt to access other users' resources → should fail
- Vision LLM validates that access is properly denied (not just a blank page)

### 7.3 Chaos actions
- Rapid back/forward navigation
- Double-clicking buttons
- Submitting forms with boundary values (empty, max-length, unicode, emoji)
- Opening same page in multiple tabs
- Navigating during async operations (deploy in progress → navigate away → come back)

---

## Deployment Options

### Option A: Standalone Docker Compose
```bash
cd stress-tester/
docker compose up -d
# Control via API
curl -X POST http://localhost:18090/runs -d '{"profile": "smoke"}'
curl http://localhost:18090/runs/{run_id}/report > report.html
```

### Option B: Kamiwaza App Garden
Register as an app template:
```yaml
services:
  stress-tester:
    image: kamiwaza/stress-tester:latest
    ports:
      - "18090:18090"
    environment:
      - KAMIWAZA_URL=https://localhost
      - KAMIWAZA_ADMIN_USER=${KAMIWAZA_ADMIN_USER}
      - KAMIWAZA_ADMIN_PASSWORD=${KAMIWAZA_ADMIN_PASSWORD}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - uat-data:/data
```
Deploy via: `POST /api/v1/apps/deploy_app` with template reference.

### Option C: K8s Job (CI/CD)
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: uat-stress-test
spec:
  template:
    spec:
      containers:
        - name: stress-tester
          image: kamiwaza/stress-tester:latest
          env:
            - name: STRESS_TESTER_PROFILE
              value: "load"
            - name: STRESS_TESTER_AUTO_RUN
              value: "true"  # Start run immediately, exit when done
          envFrom:
            - secretRef:
                name: stress-tester-secrets
      restartPolicy: Never
  backoffLimit: 0
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KAMIWAZA_URL` | Yes | — | Target Kamiwaza instance URL |
| `KAMIWAZA_ADMIN_USER` | Yes | — | Admin account for user provisioning |
| `KAMIWAZA_ADMIN_PASSWORD` | Yes | — | Admin account password |
| `ANTHROPIC_API_KEY` | For vision | — | Claude API key |
| `STRESS_TESTER_PROFILE` | No | `smoke` | Default stress profile |
| `STRESS_TESTER_AUTO_RUN` | No | `false` | Start run on container boot (for CI) |
| `STRESS_TESTER_DATA_DIR` | No | `/data` | Results storage path |
| `STRESS_TESTER_PORT` | No | `18090` | Control plane listen port |
| `STRESS_TESTER_VISION_MODEL` | No | `claude-sonnet-4-6` | Vision model for validation |
| `STRESS_TESTER_VISION_MODEL_COMPLEX` | No | `claude-opus-4-6` | Vision model for exploration |
| `STRESS_TESTER_MAX_WORKERS` | No | `20` | Max concurrent browser contexts |
| `STRESS_TESTER_SCREENSHOT_QUALITY` | No | `80` | JPEG quality (0-100, or `png`) |
| `NODE_TLS_REJECT_UNAUTHORIZED` | No | `0` | Accept self-signed certs |

---

## Implementation Order

| Phase | Deliverable | What it proves |
|-------|------------|----------------|
| **1** | Container + FastAPI + user manager + login test | Can create users, launch browsers, take screenshots |
| **2** | Browser profiles + screenshot pipeline | Multi-browser, multi-OS emulation works |
| **3** | Vision LLM integration + page validation | LLM can validate UI state from screenshots |
| **4** | YAML scenario engine + 3 core scenarios | Scripted flows run reliably |
| **5** | Stress orchestrator + concurrent workers | N users hitting the app simultaneously |
| **6** | HTML report generator | Results are viewable and shareable |
| **7** | Exploratory mode + RBAC boundary testing | LLM finds bugs humans wouldn't script |

**Start with Phase 1** — proves the concept end-to-end with the simplest vertical slice.

---

## Estimated Resource Requirements

| Profile | Browser contexts | RAM (est.) | CPU | LLM calls/min |
|---------|-----------------|------------|-----|----------------|
| smoke (3 users) | 3 | 2 GB | 2 cores | ~6 |
| load (20 users) | 20 | 12 GB | 8 cores | ~40 |
| soak (5 users, 1hr) | 5 | 4 GB | 4 cores | 0 (screenshots only) |

Each Chromium context uses ~200-400 MB RAM. Firefox and WebKit are similar.
Vision LLM calls are ~$0.003 per screenshot (Sonnet, ~1K input tokens for image).
A 20-user, 10-minute load test with vision ≈ 400 screenshots ≈ $1.20 in API costs.
