# Stress Tester

Phase 1 implementation of the Stress Tester plan:

- FastAPI control plane (`POST /runs`, `GET /runs`, `GET /runs/{id}`, `DELETE /runs/{id}` to stop, `DELETE /runs/{id}/purge` to remove run + artifacts)
- Provider-neutral review APIs (`POST /reviews/plan`, `POST /reviews`, `GET /reviews/{id}/summary`, `GET /reviews/{id}/comment`)
- Live websocket stream (`WS /live/{run_id}`)
- User provisioning and cleanup via Kamiwaza admin API
- Playwright-driven login worker with screenshot capture
- Run artifacts and report generation in `/data/runs/{run_id}`
- Component-specific UAT guidance from extension repo `.uat/` folders

## Quick start (local)

```bash
uv sync
uv run stress-tester
```

### Spin up 20 bots on a fixed path (no LLM cost)

```bash
# Terminal 1 — start the API
make stress-serve

# Terminal 2 — launch 20 bots on a predetermined scenario
make stress-list                                  # see available paths
make stress-run SCENARIO=kaizen-conversation-1    # pick a path
make stress-run SCENARIO=login USERS=50           # override the bot count
```

`stress-run` uses `vision_enabled: false` and `exploratory_pct: 0.0`, so the bots
execute the fixed YAML steps and never call an LLM. To add your own path, drop
a `<name>.yaml` into `stress_tester/scenarios/builtin/` and reference it as
`SCENARIO=<name>`.

> We use `SCENARIO=` (not `PATH=`) because setting `PATH=` on the Make command
> line overrides `$PATH` for every sub-shell — curl, python, and uv would
> stop being found.

The API can now start without Kamiwaza credentials.  
You only need `KAMIWAZA_URL` plus admin auth (`KAMIWAZA_ADMIN_TOKEN` or user/password) when launching `/runs`.
By default local runs store artifacts in `./data` (Docker compose still uses `/data`).
By default the API listens on `18090` (`STRESS_TESTER_PORT` can override this).

## EC2 / RHEL browser prerequisites

On RHEL-family hosts (including many EC2 images), install Playwright browsers plus system browser deps:

```bash
uv run playwright install chromium firefox webkit
sudo dnf install -y chromium firefox
```

Notes:
- WebKit may not run natively on some RHEL hosts; stress-tester now auto-falls back to Chromium per worker and logs the fallback event.
- If you reprovision the host, rerun the commands above.

## Docker

```bash
docker compose up --build
```

## Kamiwaza Extensions Template Integration

This folder now includes extension-template-compatible files:
- `kamiwaza.json`
- `docker-compose.appgarden.yml`
- `images/stress-tester-preview.svg`

To copy this project into a `kamiwaza-extensions-template` repo as `apps/stress-tester` and verify compatibility:

```bash
uv run python scripts/sync_to_kamiwaza_extensions_template.py \
  --template-repo /home/ec2-user/k8s/kamiwaza-extensions-template \
  --force
```

After sync, the template repo can build/publish as normal:

```bash
cd /home/ec2-user/k8s/kamiwaza-extensions-template
make build TYPE=app NAME=stress-tester
make push TYPE=app NAME=stress-tester STAGE=dev
make kamiwaza-push TYPE=app NAME=stress-tester
```

## Web UI

Open `http://localhost:18090/` for the control center:
- Start runs with preset profiles or custom values
- Preview and launch CI-style review runs locally using PR-like metadata and changed files
- Configure Kamiwaza URL/admin credentials per run (optional), with env fallback
- If the admin password/token is omitted, the server first tries the local `kamiwaza-user-admin` Kubernetes secret, then falls back to `admin` / `kamiwaza` when the secret is unavailable
- Note: some deployments require an admin token/PAT for user provisioning even if UI password login works.
- Configure scenario paths via checkboxes:
  - `Model Download / Deployment` -> `model_browse`, `model_deploy`
  - `App & Tool Deployment` -> `app_deploy`, `app_garden`, `vectordb`
  - `Add / Remove Users (Admin Path)` -> `cluster_admin`, `rbac_boundary`
- Add manual scenarios in the `Additional Scenarios` field (merged with selected path scenarios)
- Monitor run list/status in real time
- Click a run ID to open that run's report
- Delete old runs directly from the Runs table (purges all artifacts for that run)
- Watch live events and screenshot previews (with one-click copy for event lines/all)
- Copy run detail JSON with one click
- Open per-run HTML reports with metrics + screenshots + run/event logs

Service metadata is available at `http://localhost:18090/meta`.

## API examples

Preview a review plan without running it:

```bash
curl -X POST http://localhost:18090/reviews/plan \
  -H 'Content-Type: application/json' \
  -d '{
    "target_url": "https://preview.example.test/runtime/apps/kaizen/",
    "repository": "kamiwaza/stress-tester",
    "branch": "feature/review-runs",
    "commit_sha": "abc1234",
    "pr_title": "Improve chat workflow",
    "changed_files": [
      "apps/kaizen/src/components/ChatComposer.tsx",
      "apps/kaizen/src/routes/conversations/[id].tsx"
    ]
  }'
```

Start a review run:

```bash
curl -X POST http://localhost:18090/reviews \
  -H 'Content-Type: application/json' \
  -d '{
    "target_url": "https://preview.example.test/runtime/apps/kaizen/",
    "repository": "kamiwaza/stress-tester",
    "pr_title": "Improve chat workflow",
    "changed_files": [
      "apps/kaizen/src/components/ChatComposer.tsx",
      "apps/kaizen/src/routes/conversations/[id].tsx"
    ]
  }'
```

```bash
curl -X POST http://localhost:18090/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "concurrent_users": 3,
    "role_distribution": {"admin": 1, "editor": 1, "viewer": 1},
    "browser_distribution": {"chromium": 2, "firefox": 1},
    "os_emulation": ["win-chrome", "mac-firefox"],
    "scenarios": ["login"],
    "component": "graphiti",
    "duration_seconds": 120,
    "ramp_up_seconds": 15,
    "vision_enabled": false
  }'
```

Discover available `.uat` contexts:

```bash
curl 'http://localhost:18090/uat/contexts?component=graphiti'
```

Set `STRESS_TESTER_EXTENSION_ROOTS` to a comma-separated list of repo paths or globs if your extension repos live elsewhere.

Current `.uat` behavior:
- No strict file schema is required.
- If multiple extension repos match a component filter, guidance from all matches is merged.
- Run artifacts persist a noise-controlled guidance index (`analysis/uat_guidance_index.json`) with file paths, lengths, and short snippets (not full source content).
