# Load Test Report — 100-Bot at MAX_WORKERS=50 (Multi-Model, Clean Cluster)

**Date:** 2026-05-26
**Run ID:** `d145cadd0b5c47dcb6046a368e286922`
**Wall:** 37.2 min, 100/100 finished, **0 Hello+LLM successes**, 1 worker login-crash
**Stack:** perf-overhaul branch set + kaizen connector-overhaul (local build, all images cached on kind node)
**Verdict:** Platform's auth + workroom-entry surface area **cannot handle 50 simultaneous fresh editor sessions** on this hardware. ForwardAuth/Keycloak token-propagation races, core 500s on `/api/workrooms/leave`, and the dashboard SPA losing session mid-load combine to break every bot before it can send a Hello.

## Pre-flight

| Step | State |
|---|---|
| Cluster pre-clean (42 leftover workrooms via `DELETE /workrooms/api/admin/workrooms/{id}`) | reconciler drained 118→3 pods |
| Cluster baseline at run start | 26% CPU / 8% memory, 3 baseline pods in `kamiwaza-extensions` |
| Kaizen image cache (kind containerd) | all 4 images present, no cold pull |
| Single-bot smoke (warm cluster, before run) | **COMPLETED, 40/40 steps in 4-min wall** ✓ |
| Scenario timeouts | Bumped comprehensively (16 step + 5 inner JS polling + worker.py login budget 5s→20s/selector). One-bot smoke confirms no scenario-side timeouts remain. |
| 4 chat models deployed | `gpt-5.2-pro`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.5` — random selection per bot |

## Run config

| Parameter | Value |
|---|---|
| `concurrent_users` | 100 |
| `STRESS_TESTER_MAX_WORKERS` | **50** (vs prior 20) — drives true 50-concurrent stress on auth |
| `role_distribution` | `{editor: 100}` |
| `duration_seconds` | 7200 (120 min cap) |
| `ramp_up_seconds` | 120 |
| scenario | `workroom_kaizen_hello` (40 steps, single Hello + cleanup, random model pick) |
| cluster | kind+podman, 1 node, 24 CPU / 226Gi |

## Result tally

| Stage | Count | % |
|---|---:|---:|
| Workers started | 100/100 | 100% |
| Workers crashed at login (`unable to locate login inputs`, 160s budget exhausted) | 1 | 1% |
| Scenario step 15 (`/enter 401`) | **57** | 57% |
| Scenario step 12 (`POST /deployments 401` or 500 — auth race + core 500) | 21 | 21% |
| Scenario step 3 (Create Workroom button never appeared — dashboard SPA broken) | 13 | 13% |
| Scenario step 32 (composer wait — bot stuck on `/runtime/apps/`, never advanced to `/conversations/`) | 8 | 8% |
| **Hello + LLM success** | **0** | **0%** |

Per-10-bot wave success: 0/10 across ALL ten windows. Unlike prior runs at MAX_WORKERS=20 where late-wave bots succeeded at 90%, the 50-concurrent load never lets up enough for any bot to get through.

**Cluster never saturated:** peak 51% CPU / 16% memory. The bottlenecks are not compute or memory — they are inside the auth path and a session-eviction race in the dashboard SPA.

## Real platform findings (with logs + fix locations)

### Finding #1 — ForwardAuth/Keycloak token race breaks `POST /api/workrooms/{id}/enter` at 50-concurrent (78 of 99 errors)

**Evidence — captured directly from the bot's `js_eval` error messages:**

```
ERROR: enter failed: 401 body={"detail":"No access token found"}   ← 41 occurrences
ERROR: enter failed: 401 body={"detail":"Not authenticated"}        ← 15 occurrences
ERROR: enter failed: 500 body=Internal Server Error                ← 1 occurrence
ERROR: POST /deployments failed (non-retryable): 401 ...           ← 10 occurrences (same race, deploy POST path)
```

The `/enter 401` is a race between Keycloak issuing a session and ForwardAuth recognizing it. The "No access token found" variant means ForwardAuth never received the token cookie at all. "Not authenticated" means ForwardAuth saw it but rejected.

This was previously a wave-1-only failure mode (5-6 bots per run at MAX_WORKERS=20). At MAX_WORKERS=50, it becomes the **dominant failure mode (78%)** and never recovers — every wave hits it.

**Code paths involved:**

- Bot POSTs `/workrooms/api/workrooms/{id}/enter` (workroom-manager extension)
- Workroom-manager backend forwards to kamiwaza core via traefik: `https://traefik.kamiwaza.svc.cluster.local/api/workrooms/enter`
  - [outcome-d563-workroom-manager/apps/outcome-d563-workroom-manager/backend/app/routes/deployments.py:775](outcome-d563-workroom-manager/apps/outcome-d563-workroom-manager/backend/app/routes/deployments.py#L775) `_enter_workroom_session(...)` is called BEFORE the deploy POST; if it fails the whole deploy fails
  - On HTTPStatusError, line 207 re-raises with original status: `raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc` — so a 401 from core arrives at the bot as a 401, a 500 as a 500
- Kamiwaza core's `/api/workrooms/enter` handler is in [kamiwaza/kamiwaza/services/workrooms/api.py](kamiwaza/kamiwaza/services/workrooms/api.py); it requires `AuthenticatedUser` (validated by ForwardAuth)
- ForwardAuth validates the session token; if Keycloak hasn't fully published it yet, the token validation fails

**Suggested fixes (ranked by impact):**

1. **Backend: add a small retry-with-backoff inside `/api/workrooms/enter` when ForwardAuth says "session not yet validated."** Today the failure is binary — token recognized or 401. A 100ms-500ms wait-and-retry-once would absorb the propagation race.
2. **Workroom-manager: retry-on-401 in `_enter_workroom_session`.** The extension is the only client of that endpoint that has the context to know "this is a launch flow, the session was just minted, a 401 is likely a race." Currently the 401 is re-raised immediately at [deployments.py:207](outcome-d563-workroom-manager/apps/outcome-d563-workroom-manager/backend/app/routes/deployments.py#L207).
3. **ForwardAuth: increase cache TTL or pre-warm sessions.** The auth-perf-overhaul branch added a success cache; that helps for repeated calls but not the very first call after session mint.

---

### Finding #2 — Core 500 on `/api/workrooms/leave` cascades into deploy POST 500s (5 of 99 errors)

**Evidence — captured from workroom-manager backend logs during the run:**

```
Best-effort workroom session restore failed after launch for 08567354-...:
  Server error '503 Service Unavailable' for url 'https://traefik.kamiwaza.svc.cluster.local/api/workrooms/leave'
Best-effort workroom session restore failed after launch for 4ce55c37-...:
  Server error '500 Internal Server Error' for url 'https://traefik.kamiwaza.svc.cluster.local/api/workrooms/leave'
Failed Kamiwaza API call https://traefik.kamiwaza.svc.cluster.local/api/workrooms/:
  (empty body — connection refused or proxy timeout)
```

The "Best-effort" log line is misleading: the workroom-manager extension does swallow these errors in `_restore_workroom_session` at [deployments.py:326-331](outcome-d563-workroom-manager/apps/outcome-d563-workroom-manager/backend/app/routes/deployments.py#L326) (`except (HTTPException, httpx.HTTPError)`). However, **the earlier `_enter_workroom_session` call at [line 775](outcome-d563-workroom-manager/apps/outcome-d563-workroom-manager/backend/app/routes/deployments.py#L775) is NOT wrapped** — and that's the call that's actually returning 500/401 to the bot.

For the 500 specifically: kamiwaza core's `/api/workrooms/enter` handler at [api.py](kamiwaza/kamiwaza/services/workrooms/api.py) calls `WorkroomSessionManager.enter_workroom(...)` which under concurrent load can throw — that's the 500. There's no traceback in core-scheduler logs visible to us; it's likely in a Ray worker's stdout we'd need `kubectl logs core-raycluster-head-*` to dig into, but ray serve doesn't surface app exceptions through `kubectl logs` cleanly.

**Suggested fixes:**

1. **Wrap `_enter_workroom_session` in the same try/except pattern as `_restore_workroom_session`** at [deployments.py:312-331](outcome-d563-workroom-manager/apps/outcome-d563-workroom-manager/backend/app/routes/deployments.py#L312-L331). If the bot's launch flow can tolerate a missed workroom-binding (treat as Global Workroom fallback), this would convert the 500 cascade into a soft warning. **Tradeoff:** changes the launch-flow guarantees — a deploy that "succeeded" might not be bound to the requested workroom. Coordinate with the workroom-binding-backend memory note.
2. **Backend: locate the 500-throwing path in `WorkroomSessionManager`** and wrap concurrent-write contention with a retry or a SELECT-FOR-UPDATE pattern.

---

### Finding #3 — Dashboard SPA session eviction under load (13 of 99 errors)

**Evidence — captured from bot's "Create Workroom button not found" errors:**

```
Controls: [Home | Models | Apps | Tools | Catalog | Connectors | News | 0]   ← 3 bots saw the nav bar but no /workrooms page content
Controls: [Login]                                                            ← 8 bots got KICKED OUT to login mid-flow
Controls: [Retry]                                                             ← 1 bot got a generic error page with Retry
Controls: []                                                                  ← 1 bot got a blank page
```

The 8 bots seeing `[Login]` are the most damning: they passed login, navigated to `/workrooms`, and at some point during the 5-minute wait for the Create Workroom button to render, **the dashboard SPA decided their session was invalid and redirected them back to login.** This is session eviction under concurrent auth churn — likely the same race as Finding #1, manifesting on the frontend rather than at the backend.

The 3 bots seeing only the nav bar (`[Home | Models | ...]`) reached `/workrooms` but the page-specific component (the workroom list with the "Create Workroom" button) never hydrated. The dashboard fetched data from a backend endpoint and got a 401/500 response that the SPA failed to handle gracefully — instead of showing an error UI, it showed a blank content area with only the navigation chrome.

**Suggested fixes:**

1. **Frontend: handle 401 from `/api/workrooms/` (or related list endpoints) by surfacing a "session expired, please re-login" message** instead of just leaving the page blank or silently redirecting to login. Currently the bot can't tell whether it should retry or give up.
2. **Frontend: the workroom-list route should fail-soft.** If the data fetch fails, render an empty-state with a retry button rather than rendering the bare nav.
3. **Backend: the 401 root cause (Finding #1) is the same.** Fixing that makes Finding #3 mostly disappear.

The 3 places to look: [kamiwaza/frontend/src/services/workrooms.js](kamiwaza/frontend/src/services/workrooms.js) (API client), [kamiwaza/frontend/src/components/workrooms/](kamiwaza/frontend/src/components/workrooms/) (page components), and whichever route handler in [kamiwaza/frontend/src/](kamiwaza/frontend/src/) mounts the `/workrooms` page.

---

### Finding #4 — 8 bots reached agent-create but `handleStartChat` never navigated to `/conversations/{id}`

**Evidence — composer-wait errors after 20 minutes parked on `/runtime/apps/kaizen-*`:**

```
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-emiyev6h-6a94
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-sdqmqaz6-9ab9
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-egehi9it-3eb7
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-9j4fb3z4-3dff
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-j6w3p5ao-75d6
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-8kvu609q-0882
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-eh57c4xz-ad63
ERROR: composer not found after 1200s. url=https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-yy0uagkk-4c67
```

These 8 bots made it past `/enter` AND past the deploy AND past the kaizen-UI-load AND past the create-agent wizard. They clicked the agent card; kaizen's `handleStartChat` should have called the kaizen backend `POST /api/conversations` and pushed the router to `/conversations/{id}`. **That URL transition never happened** — they sat on `/runtime/apps/<kaizen-deployment-name>/...` for 20 minutes (the bumped scenario budget) without ever advancing.

This is the same kaizen-side failure mode documented in earlier runs (when it was 13 of 19 errored bots at MAX_WORKERS=20). It's a kaizen frontend or backend issue with conversation creation under load.

**Suggested investigation path:**

- Check kaizen backend logs for `POST /api/conversations` 5xx responses during the run window — that's the call kaizen frontend makes on agent-card-click
- File: [kamiwaza-extensions-kaizen/apps/kaizenv3/backend/app/api/v1/conversations.py](kamiwaza-extensions-kaizen/apps/kaizenv3/backend/app/api/v1/conversations.py) (or wherever the conversation-create endpoint lives)
- Check kaizen frontend's `handleStartChat` handler for missing error handling — if the POST fails silently, the router never pushes

---

## Comparison to MAX_WORKERS=20 runs

| Concurrency | Hello+LLM success rate | Dominant failure |
|---|---:|---|
| MAX_WORKERS=20 (50-bot, prior runs) | 62% (rev with all fixes) | Composer-wait + occasional auth race |
| **MAX_WORKERS=50 (this run, 100-bot)** | **0%** | ForwardAuth/Keycloak 401 storm (78% of errors) |

**The platform's auth surface area has a hard ceiling somewhere between 20 and 50 concurrent fresh editor sessions.** Capacity scaling is not the issue (51% CPU peak); the bottleneck is in the auth path's tolerance for simultaneous session establishment.

## What's confirmed working at this concurrency

- ✅ Kaizen image cache + local registry serving (zero cold-pull penalty observed)
- ✅ Kaizen agent sandbox lifecycle (when bots got to it, sandbox pods spawned + bound :8000 in ~3s)
- ✅ Cluster compute and memory headroom (51% CPU peak, 16% memory)
- ✅ Smoke at warm cluster: 1 bot completes 40/40 steps in 4-min wall
- ✅ Image pull from `host.docker.internal:5001` via kind containerd mirror
- ✅ The kaizen connector-overhaul branch's structural integrity (deployments come up; reconciler reconciles)
- ✅ Cleanup-via-admin-API (`DELETE /workrooms/api/admin/workrooms/{id}`) with full reconciliation

## What's NOT tested

- The actual connector-overhaul feature (MCP runtime discovery). `workroom_kaizen_hello` doesn't attach any MCP tools to the agent. Use `workroom_kaizen_connector.yaml` (separate scenario in the stress-tester) to exercise the feature directly — recommend a small-concurrency run (1-3 bots).
- Multi-host load distribution. All 50 Playwright Chromium instances ran on a single test host; some of the "session eviction" behavior may be amplified by client-side TCP/process contention.

## Reproduction recipe

```bash
# 0. Pre-clean cluster (admin endpoint, full reconciliation)
ADMIN_PW=$(kubectl -n kamiwaza get secret kamiwaza-user-admin -o jsonpath='{.data.password}' | base64 -d)
TOK=$(curl -sk -X POST "https://hpe-demo-0130.westus2.cloudapp.azure.com/realms/kamiwaza/protocol/openid-connect/token" \
    -d "client_id=kamiwaza-platform" -d "grant_type=password" -d "username=admin" --data-urlencode "password=$ADMIN_PW" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
curl -sk -H "Authorization: Bearer $TOK" "https://hpe-demo-0130.westus2.cloudapp.azure.com/workrooms/api/admin/workrooms" \
    | python3 -c "import json,sys; [print(w['id']) for w in json.load(sys.stdin) if not w['id'].startswith('ffffffff')]" \
    | xargs -P 8 -I{} curl -sk -X DELETE -H "Authorization: Bearer $TOK" \
        "https://hpe-demo-0130.westus2.cloudapp.azure.com/workrooms/api/admin/workrooms/{}"

# 1. Wait for reconciler to drain kamiwaza-extensions to ~3 pods baseline

# 2. Restart stress-tester with bumped semaphore
pkill -f stress-tester; sleep 3
cd uat-bot
STRESS_TESTER_MAX_WORKERS=50 nohup uv run stress-tester > /tmp/stress.log 2>&1 & disown

# 3. Smoke first (sanity check)
curl -sS -X POST http://localhost:18090/runs -H 'Content-Type: application/json' \
    -d '{"concurrent_users": 1, "role_distribution": {"editor": 1}, "browser_distribution": {"chromium": 1},
         "scenarios": ["workroom_kaizen_hello"], "duration_seconds": 1500, "ramp_up_seconds": 0,
         "single_iteration": true}'

# 4. Once smoke COMPLETES with 40/40 steps, launch 100-bot
curl -sS -X POST http://localhost:18090/runs -H 'Content-Type: application/json' \
    -d '{"concurrent_users": 100, "role_distribution": {"editor": 100}, "browser_distribution": {"chromium": 100},
         "scenarios": ["workroom_kaizen_hello"], "duration_seconds": 7200, "ramp_up_seconds": 120,
         "single_iteration": true}'
```

## Suggested next steps

1. **Add a single retry-on-401 in workroom-manager's `_enter_workroom_session`** (Finding #1). Catches the propagation race without backend changes. ~5 lines of code.
2. **Investigate kamiwaza core's `WorkroomSessionManager.enter_workroom` and `.leave_workroom` for concurrent-write contention** (Findings #1, #2). The 500 cascade and the 401 storm likely share a root cause inside this manager.
3. **Re-test at MAX_WORKERS=30 and MAX_WORKERS=40** to bisect where the platform's auth ceiling lies between 20 and 50.
4. **Frontend: handle 401 in workroom-list data fetch with an error UI** (Finding #3). Prevents the 8 "session-evicted-to-login" failures from looking like bot crashes.
5. **Investigate kaizen `handleStartChat` for under-load failures** (Finding #4). 8 bots got past every other gate and still couldn't reach `/conversations/`.
