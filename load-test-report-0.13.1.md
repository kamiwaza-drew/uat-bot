# Load Test Report — Kamiwaza 0.13.1 vs 0.13.0 Workroom-Launched Kaizen Flow

**Date:** 2026-05-23
**Target build under test:** Kamiwaza `release/0.13.1` (`core` + `frontend` images pulled from GHCR `:release-0.13.1`)
**Comparison baseline:** Kamiwaza `release/0.13.0` (`:develop` core image at the time)
**Host:** `kamiwaza-dev-control-plane` — single-node kind+podman cluster on `hpe-demo-0130.westus2.cloudapp.azure.com`
**Driver:** `uat-bot` stress-tester, scenario `workroom_kaizen_ctx`
**Bot population for the headline test:** **20 concurrent admin users** (was 1 per run on 0.13.0)

## Executive summary

0.13.1 **does measurably improve the deploy-time path** — a single workroom-launched Kaizen reaches a usable UI in **~2 minutes vs ~10 minutes on 0.13.0**, and the graphiti CrashLoop pattern from the 0.13.0 report did not reappear. **But the architectural ceilings called out in the 0.13.0 report all still hold under real concurrent load**: the cluster wedges at the kubelet pod cap, the API still accepts deploys it can't schedule, no GC happens, and a *new* failure mode surfaces under concurrency — the kamiwaza-core auth layer rejects valid sessions with `401 Not Authenticated` when ~15+ near-simultaneous requests hit it.

The platform is **stable enough for small dev/demo workloads** on 0.13.1 (single-user, sequential workrooms). It is **not stable for any multi-user scenario** that creates more than ~5 workrooms in a short window.

## Methodology delta from 0.13.0 report

Same `workroom_kaizen_ctx` scenario, same Kamiwaza host, but two changes that matter:

1. **20 concurrent bots** (was 1). This is the actual stress-test the 0.13.0 report could only theorize about.
2. **Cluster pre-test cleanup**: starting pod count 78, 0 Pending, fresh after a soft-delete of 21 abandoned ctx-mgr-uat workrooms from the prior campaign. So results reflect 0.13.1 under a clean baseline — not the accumulated saturation that biased the 0.13.0 run.

`ramp_up_seconds=30`, `duration_seconds=1800`, single iteration per worker, admin login (`skip_user_provisioning=true`).

## Headline result: 20-bot stress run on 0.13.1

| Stage | Bots reaching it |
|---|---:|
| Login + navigate to /workrooms | 17 / 20 |
| Workroom created via wizard | 17 / 20 |
| Deploy POST returned + Kaizen pods scheduled | 16 / 20 |
| Kaizen UI actually loaded (composer step) | **1 / 20** |
| Scenario completed fully | **0 / 20** |

The run reported `status=COMPLETED completed=20 failed=0` at the stress-tester API level — misleading per the report finding, every scenario errored mid-flight.

### Failure-mode breakdown by first error per worker

| Count | Failure | Layer |
|---:|---|---|
| **15** | `enter failed: 401 {"detail":"Not authenticated"}` after Kaizen pods scheduled | kamiwaza-core auth, under concurrent load |
| 2 | Landed on `Login` page instead of `/workrooms` | keycloak / auth-gateway dropped session during initial nav |
| 1 | Landed on `Retry` page (transient backend 5xx) | core API |
| 1 | `Page.goto: Timeout 60000ms exceeded` waiting for networkidle | frontend / network |
| **1** | Reached Kaizen UI, hit "No agents yet" (scenario lacks agent-create step) | scenario-coverage gap, not a platform bug |

The 15-of-20 auth-gateway 401s are the **new finding** that only became visible at concurrency. Each of those workers had:

- successfully POSTed `/workrooms/api/deployments` (kaizen pods got created)
- successfully observed the kaizen URL become routable via fetch-poll
- then hit `POST /api/workrooms/{id}/enter` on kamiwaza-core → 401

Same session cookie that passed the earlier API calls is suddenly rejected. The auth layer can't sustain the burst even though the sessions are valid.

## Cluster behavior during the 20-bot run

Timeline of pod budget on the single 110-pod node:

| Time | Total | Running | Pending | FailedScheduling events |
|---:|---:|---:|---:|---:|
| pre-test | 78 | 66 | 0 | 0 |
| T+30s | 99 | 73 | 9 | 0 |
| T+45s | 106 | 84 | 3 | 0 |
| T+1m | 122 | 94 | 7 | 4 |
| T+1.5m | 168 | 100 | 50 | 62 |
| T+2m | 190 | 100 | 72 | 85 |
| T+2.5m | 210 | 100 | 92 | 106 |
| T+3m | 218 | 100 | 100 | 114 |
| T+4m | 222 | 100 | 104 | 134 |
| T+7m | 222 | 100 | 104 | 211 |

Running pods plateaued at exactly 100 (the practical kubelet ceiling on this node). Pending climbed to 104. **211 FailedScheduling events total.** Same exact wedge shape as the 0.13.0 report — the platform has no backpressure regardless of release.

## What 0.13.1 actually fixed vs left in place

| Issue from 0.13.0 report | Status on 0.13.1 |
|---|---|
| Per-workroom pod cost ~11 (kaizen×4 + milvus×4 + graphiti×2 + omniparse) | Unchanged — same shape, same ~7-workroom ceiling on a 110-pod node |
| **Graphiti/Neo4j CrashLoopBackOff (no resource limits)** | **Resolved** — no graphiti CrashLoops observed in this run. 1 milvus CrashLoop instead, qualitatively much better than the ~10 graphiti loops from the 0.13.0 campaign. The 0.13.1 graphiti subchart's CPU/memory caps appear to be working. |
| No API-level backpressure when scheduler is saturated | Unchanged — 20/20 deploy POSTs accepted, 100+ pods Pending forever |
| No quota per user / per workroom | Unchanged |
| No TTL / GC on abandoned workrooms | Unchanged — Pending pods from this run will persist until an operator cleans up |
| Misleading run-level "COMPLETED" status that masks scenario errors | Unchanged (stress-tester bug, not 0.13.1) |
| First-deploy time | **Improved**: ~10 min → ~2 min for the URL to become routable. Big developer-experience win. |
| **NEW** — auth-gateway drops valid sessions under burst load | **Regression or newly-exposed limit** — wasn't visible in single-user 0.13.0 testing because the test never had concurrent admin sessions. |

## What this means for 0.13.1

- **Single-user / sequential workflows**: noticeably better than 0.13.0. The deploy speedup and the Graphiti stability fix both land.
- **Multi-user / concurrent workflows**: same wedge as 0.13.0, plus a new auth-burst failure that needs investigation. A 5-person QA team or sales demo creating workrooms in parallel will still wedge this cluster within minutes, and 75% of users will see `401 Not Authenticated` errors that the UI presents as opaque failures.
- **The 0.13.0 architectural recommendations stand unchanged**: shared Milvus/Graphiti instead of per-workroom (drops cost from 11 to ~3 pods, lifts ceiling from 7 to ~25 workrooms), TTL on abandoned workrooms, API-level backpressure, per-user quota.

## Recommended fixes (consolidated, priority order)

### 1. Reduce per-workroom pod cost — the only durable fix for the cluster wedge

The cluster wedged at 100 Running / 100+ Pending under 20 bots because each workroom needs ~11 pods. Concrete design changes (largest leverage first):

- **Shared Milvus per cluster** instead of per workroom — drops 4 pods per workroom to 0 marginal. The Global Workroom already runs a shared `service-wr1-milvus-*` instance; extend the same pattern to user workrooms via collection-level isolation.
- **Shared Graphiti/Neo4j per cluster** with database-level isolation — drops 2 pods to 0 marginal.
- **Lazy provisioning of vectordb / graph stores** — don't deploy Milvus + Graphiti + Omniparse at workroom-create time. In this campaign every workroom got the full allocation but none ingested any content. Defer until first use of the feature that needs them.
- **Consolidate Kaizen containers** — `kaizen-postgres` and `kaizen-sandbox-controller` could plausibly run as sidecars in the backend pod. Cuts kaizen from 4 → 2 pods.

Just (a) + (b) drops per-workroom cost from ~11 to ~3 pods, **lifting the single-node ceiling from 7 to ~25 concurrent workrooms** with no other change.

### 2. Investigate auth-gateway concurrency (0.13.1-specific, new in this run)

15 of 20 workers hit `401 Not Authenticated` on `POST /api/workrooms/{id}/enter` with valid session cookies that had already authenticated successfully on earlier calls in the same run. This was not visible in 0.13.0 because single-user testing never had concurrent admin sessions. Hypotheses worth checking:

- Auth-gateway has a per-session or per-user concurrency limit that drops sessions when crossed
- Keycloak token validation backpressures under burst and the gateway turns slow-responses into 401s
- Concurrent sessions for the same user (admin) are stepping on each other in workroom-binding state
- Rate-limiting middleware is misfiring on legitimate traffic

The 20-bot run's `data/runs/42b326ad147240569d065671af5d5543/events.jsonl` has exact request timing for correlation against keycloak / auth-gateway logs.

### 3. Workroom lifecycle / TTL — close the leak

The create wizard exposes a "Temporary workroom" toggle ("Destroyed on logout — for field/denied-area use") implying intent to auto-destroy. Two follow-ups:

- **Verify `is_ephemeral=true` workrooms actually destroy on session end.** Pending pods 3+ hours old in prior campaigns suggest the destroy hook isn't firing reliably.
- **TTL on persistent workrooms with no activity** — auto-archive after, say, 24h idle.
- **Fail-fast on stuck deploys** — if a workroom's pods are `Pending` for > 5 min, mark the deployment FAILED, surface that in the panel, and delete the underlying Deployment objects so the scheduler stops trying. This was the dominant pattern in the 20-bot run (104 Pending pods at the end, all of which will sit forever until operator cleanup).

### 4. Cluster-side backpressure

The API accepted 20/20 deploy POSTs even when the scheduler couldn't fulfill them. User-facing impact: "Initializing…" forever with no feedback.

- **Reject deploy requests when scheduler is at capacity** — check recent `FailedScheduling` events or pending-pod count; return 503 with a useful message
- **Per-user workroom quota** (admin-configurable, e.g., 5 concurrent workrooms per user)
- **Surface "your workroom is queued — cluster is at capacity"** in the UI instead of the perpetual "Initializing…" badge

### 5. Stress-tester reporting fix (tooling, not platform)

The 20-bot run reported `status=COMPLETED completed=20 failed=0` even though all 20 scenarios errored. The runner reports COMPLETED whenever the worker process exits cleanly, regardless of scenario outcome. Surface scenario success/failure in the run-level status. Already noted in the SKILL.md change merged earlier today on the marketplace plugin.

### 6. Marketplace extension-push image tag mismatch (uncovered while restoring extensions)

The `kamiwaza-engineering-marketplace` push pipeline tags extension images as `<version>-dev` when run with `STAGE=dev` (default). For `workroom-manager 0.6.19`, GHCR has `:0.6.19` but the pushed catalog template references `:0.6.19-dev`, which doesn't exist. Manual fix in this report: kubectl-patched the Deployment image. Pipeline fix: build + push the `:0.6.19-dev` tag during the marketplace publish so dev-stage installs match, OR omit the `-dev` suffix when the underlying image only has the unsuffixed tag.

## Suggested next test

Once shared Milvus + shared Graphiti are designed in, re-run this same 20-bot scenario to validate the architectural fix. The headline metric would be: how many of 20 bots reach the Kaizen UI within their 30-min timeout? **Target: ≥18/20 (allow for transient flakes), with no 401 storm and ≤30 FailedScheduling events total.**

## Caveats on this report

- Scenario does not include an agent-create step; even the 1 bot that reached the Kaizen UI couldn't actually send messages. This is a stress-tester scenario gap, not a 0.13.1 platform issue. The original goal of "exercise the context manager via 3 conversations" remains untested on either version. The platform-layer findings here stand independently.
- I broke `workroom-manager` and `skills-library` extensions partway through this campaign during cleanup over-reach. They were restored via the UI install flow before the 20-bot run. Restoration uncovered a separate bug: the marketplace push tags images as `:0.6.19-dev` which doesn't exist on GHCR — actual published tag is `:0.6.19`. Patched the Deployment manually to fix; worth fixing in the push pipeline.
