# Load Test Report — Kamiwaza 0.13.1 vs 0.13.0 Workroom-Launched Kaizen Flow

**Date:** 2026-05-24 (rev 2 — full-stack 0.13.1 re-pin)
**Target build under test:** Kamiwaza `release/0.13.1` across **every repo with a `release/0.13.1` branch** (rev 1 only pinned `core` + `frontend`).
**Comparison baseline:** Kamiwaza `release/0.13.0` (`:develop` core image at the time)
**Host:** `kamiwaza-dev-control-plane` — single-node kind+podman cluster on `hpe-demo-0130.westus2.cloudapp.azure.com`
**Driver:** `uat-bot` stress-tester, scenario `workroom_kaizen_ctx`
**Bot population for the headline test:** **20 concurrent admin users** (was 1 per run on 0.13.0)

## What changed since rev 1

Rev 1 of this report pinned only the **Kamiwaza platform** to `release/0.13.1` (core + frontend) and left the extension stack on whatever happened to be cached on the node. After feedback ("Bad — entire stack where possible should be 0.13.1") rev 2 walks every cloned repo to `release/0.13.1` if that branch exists on the remote. The 20-bot stress run was re-fired against this uniform stack and the failure profile shifted — the 401 auth-gateway burst from rev 1 did not reappear, but a new dominant failure (10/20 timing out on `Page.goto /workrooms`) emerged. The architectural ceiling (cluster wedges at 100 Running pods) is identical.

See "Source pin-down" below for exact branch + commit per repo.

## Source pin-down (full 0.13.1 stack used for rev 2)

All repos checked out to `release/0.13.1` HEAD where the branch exists on remote. Where it does not, fall back is noted.

| Repo                                                | Branch              | HEAD     | Notes |
|---|---|---|---|
| `kamiwaza` (platform core + frontend)               | `release/0.13.1`    | `9e14514b4` | Core + frontend pods running `ghcr.io/.../core:release-0.13.1` and `frontend-dev:release-0.13.1` |
| `deploy` (helm charts)                              | `release/0.13.1`    | `87288f2` | Used for cluster bring-up via `make dev-full` |
| `operators` (KamiwazaExtension operator)            | `release/0.13.1`    | `8b17d86` | `operators/images/extension-operator:release-0.13.1` |
| `containers` (base images: etcd, postgres, keycloak, traefik, kafka, neo4j, opensearch, milvus, graphiti, vespa) | `release/0.13.1` | `42e1205` | Tagged base images already on cluster |
| `kamiwaza-sdk`                                      | `release/0.13.1`    | `39d0e5b` | |
| `kamiwaza-docs`                                     | `release/0.13.1`    | `037b68f` | |
| `kamiwaza-extensions-kaizen`                        | `release/0.13.1`    | `174d1d5` | Image tag `1.8.13-dev` (extension uses own version, not Kamiwaza version) |
| `kamiwaza-extensions-milvus`                        | `release/0.13.1`    | `d979b09` | Image tag `2.2.0` per source; **catalog requests `2.3.0` which is not on GHCR — see Finding #2** |
| `kamiwaza-extensions-graphiti`                      | `release/0.13.1`    | `35c77ca` | Image tag `2.2.10-dev` (per ENG-5447 resource caps) |
| `kamiwaza-extensions-omniparse`                     | `release/0.13.1`    | `ce6ae6c` | Image tag `2.0.14` |
| `kamiwaza-extensions-dde`                           | `release/0.13.1`    | `5761b5a` | |
| `kamiwaza-extensions-vespa`                         | `release/0.13.1`    | `884c45d` | |
| `kamiwaza-extensions-skills-library`                | `release/0.13.1`    | `60f801a` | **Only extension with a published `:release-0.13.1` GHCR tag** |
| `outcome-d563-workroom-manager`                     | `release/0.13.1`    | `a731992` | Running `:0.6.19-dev` from cached layers (tag never published to GHCR) |
| `kamiwaza-extensions-template`                      | `develop` (no 0.13.1 branch) | `c51ac7e` | Template repo only; not deployed |

### Image-tag reality check (audited via GHCR API 2026-05-24)

| Image                                                              | `:release-0.13.1` tag on GHCR? |
|---|---|
| `kamiwaza/images/core`                                             | ✅ yes |
| `kamiwaza/images/frontend-dev`                                     | ✅ yes |
| `kamiwaza-extensions-skills-library/images/skills-library-backend` | ✅ yes |
| `kamiwaza-extensions-kaizen/images/backend` (+ frontend, controller, agent) | ❌ only `:1.8.13-dev`, `:develop`, `:pr-NNN` |
| `kamiwaza-extensions-milvus/images/service-milvus`                 | ❌ only `:develop`, `:pr-19` |
| `kamiwaza-extensions-graphiti/images/service-graphiti`             | ❌ only `:2.2.10` / `:2.2.10-dev` (last build Apr 2026) |
| `kamiwaza-extensions-omniparse/images/omniparse`                   | ❌ only `:develop` |
| `kamiwaza-extensions-dde/images/dde`                               | ❌ only `:develop` |
| `kamiwaza-extensions-vespa/images/service-vespa`                   | ❌ only `:develop` |
| `outcome-d563-workroom-manager/images/...`                         | ❌ only `:develop` (cached `:0.6.19-dev` on node from prior local push) |

**This is the corrected pin-down**: only `core`, `frontend`, and `skills-library` publish a Kamiwaza-version-aligned tag. Every other extension is on `:develop` from the same source branch (`release/0.13.1`) or on cached layers from a prior local build. The test exercises 0.13.1 source for the *platform* and the *extension repos* — but the actual GHCR image artifact for extensions is `:develop`, not a 0.13.1-aligned tag.

This is itself a **CI / release-engineering finding** — see Finding #3.

## Executive summary

0.13.1 **does measurably improve the deploy-time path** — a single workroom-launched Kaizen reaches a usable UI in **~2 minutes vs ~10 minutes on 0.13.0**, and the graphiti CrashLoop pattern from the 0.13.0 report did not reappear. **But the architectural ceilings called out in the 0.13.0 report all still hold under real concurrent load**: the cluster wedges at the kubelet pod cap, the API still accepts deploys it can't schedule, no GC happens, and *new* failure modes surface under concurrency — the frontend's `/workrooms` route can't render within 60s when ~10 sessions hit it together, and (rev-1 data) the auth-gateway returns `401 Not Authenticated` for valid sessions under a separate burst pattern.

The platform is **stable enough for small dev/demo workloads** on 0.13.1 (single-user, sequential workrooms). It is **not stable for any multi-user scenario** that creates more than ~5 workrooms in a short window.

## Methodology

Same `workroom_kaizen_ctx` scenario, same Kamiwaza host, two changes from the 0.13.0 baseline campaign:

1. **20 concurrent bots** (was 1). This is the actual stress-test the 0.13.0 report could only theorize about.
2. **Cluster pre-test cleanup**: starting pod count ~45 (single-node, after deleting 56 abandoned workroom-spawned KamiwazaExtension CRs from the rev-1 campaign). So results reflect 0.13.1 under a clean baseline.

`ramp_up_seconds=30`, `duration_seconds=1800`, single iteration per worker, admin login (`skip_user_provisioning=true`, `kamiwaza_url=https://hpe-demo-0130.westus2.cloudapp.azure.com`).

## Headline result: 20-bot stress run on rev-2 (full 0.13.1)

Run `20d7fa694ead49be8fbbd95edd03c327`, started 2026-05-24T17:18:54Z, stopped early at T+~6min once steady-state failure profile was established (the 8 still-running workers were spinning their 30-min scenario timeouts with no chance of finishing).

| Stage | Bots reaching it |
|---|---:|
| Login + navigate to /workrooms | **10 / 20** |
| Workroom created via wizard | 10 / 20 |
| Deploy POST returned + Kaizen pods scheduled | 9 / 20 |
| Kaizen UI actually loaded (`07_kaizen_ui_loaded` screenshot) | **6 / 20** |
| Scenario completed fully | **0 / 20** |

### Per-worker outcome breakdown

| Count | Outcome | Where |
|---:|---|---|
| **10** | `Page.goto: Timeout 60000ms exceeded` on initial nav to `/workrooms` | workers 008–010, 014–020. Frontend can't render the workrooms page within 60s under concurrent admin sessions. |
| 2 | `js_eval ERROR: workroom_id not found by name=ctx-mgr-uat-…` after deploy POST | workers 003, 004. Deploy returned but the workroom never materialized in the listing API. |
| 1 | `ERROR: composer not found after 150s` on Kaizen UI | worker 001. Kaizen pod scheduled + URL routable, but the in-Kaizen composer never appeared. |
| 1 | Still mid-deploy at `06_deploy_started` when run was cancelled | worker 013. |
| **6** | Reached `07_kaizen_ui_loaded` screenshot then stuck on later steps when cancelled | workers 002, 005, 006, 007, 011, 012. **These are the success-class workers** — they got further than any worker in the rev-1 run. |

The "Page.goto timeout" failure mode is the **new dominant failure for rev 2** and was not visible in rev 1. The 15-of-20 auth-gateway 401s seen in rev 1 did **not** reappear in this run — but a different bottleneck (frontend render under concurrent load) took its place. Both are symptoms of the same root cause: there is no concurrency budget anywhere in the platform.

## Cluster behavior during the run

Timeline of pod budget on the single 110-pod node:

| Time     | Total | Running | Pending | ImagePullBackOff | ext-pods |
|---:|---:|---:|---:|---:|---:|
| pre-test | ~45 | 38 | 0 | 2 | 5 |
| T+30s    | ~60 | 42 | 0 | 5 | 9 |
| T+60s    | ~70 | 54 | 0 | 5 | 23 |
| T+91s    | ~100 | 65 | 13 | 9 | 51 |
| T+121s   | ~109 | 90 | 4 | 11 | 64 |
| T+151s   | ~120 | 96 | 4 | 12 | 76 |
| T+182s   | ~120 | **100** | 3 | 10 | 76 |
| T+303s   | ~120 | **100** | 3 | 10 | 76 |
| T+333s   | ~120 | **100** | 3 | 10 | 76 |

Running pods plateaued at exactly **100** (the practical kubelet ceiling on this node), Pending plateaued at 3, ImagePullBackOff plateaued at ~10. Steady-state wedge ≈ T+3 min and never recovered. **Same shape as rev 1 and the 0.13.0 report** — the platform has no backpressure regardless of release.

## Findings (consolidated across rev 1 + rev 2)

### Finding #1 — Per-workroom pod cost is unchanged at ~11 pods (architectural ceiling)

A single workroom spawns: kaizen×4 (backend, frontend, controller, postgres) + milvus×4 + graphiti×2 + omniparse×1. On the 110-pod single-node cluster, ceiling is ~7 concurrent workrooms before the scheduler runs out of room. This was the prediction from the 0.13.0 report and rev 2 confirms it stands on 0.13.1.

### Finding #2 — Marketplace catalog requests `service-milvus:2.3.0` which doesn't exist on GHCR (new in rev 2)

When workroom-manager (running `:0.6.19-dev` from cached layers) deploys a new workroom, it requests `ghcr.io/kamiwaza-internal/kamiwaza-extensions-milvus/images/service-milvus:2.3.0`. That tag has never been published — only `:develop` and `:pr-19` exist. Every new workroom's milvus pod goes ImagePullBackOff. The pre-existing milvus pods that were already cached on the node (from prior runs) survived; new ones die.

This is the source of the 10 ImagePullBackOff pods seen at steady state. It also means the test results are **conservative** — under a fresh kind cluster with no cached images, the milvus-pull failure would cascade much harder.

`apps/service-milvus/kamiwaza.json` on `kamiwaza-extensions-milvus` `release/0.13.1` declares `version: "2.2.0"`. Where the `2.3.0` request comes from is not in the workroom-manager source tree — it appears to be in the workroom-manager's runtime catalog cache. Worth a focused investigation.

### Finding #3 — Extension CI doesn't publish `:release-0.13.1` tags

Only `kamiwaza-extensions-skills-library` has a `:release-0.13.1` GHCR tag despite all 8 extension repos having a `release/0.13.1` branch. The rest only publish `:develop`, `:pr-NNN`, and their own intrinsic version (e.g. kaizen `:1.8.13-dev`). This makes "deploy 0.13.1 to a fresh cluster" actually impossible without local builds — the platform pulls `core:release-0.13.1` cleanly but every extension would fall back to `:develop` or fail outright.

Two pipeline fixes worth considering:
- On any push to a `release/<version>` branch, also publish `:release-<version>` and `:<version>-rc<n>` tags.
- Add a sanity check in the marketplace catalog: every image referenced in `marketplace.config.json` must resolve to a real GHCR manifest at publish time.

### Finding #4 — Frontend `/workrooms` route can't render under ~10 concurrent admin sessions (new in rev 2)

10 of 20 workers hit `Page.goto: Timeout 60000ms exceeded` on the very first navigation to `/workrooms`, even though kamiwaza-core was healthy and the cluster wasn't saturated yet (T+60s, ~70 total pods). Hypotheses worth checking:

- Frontend SSR / hydration is doing N+1 API calls per session and the bursts amplify latency
- The frontend's data-fetch on `/workrooms` cascades through `/workrooms/api/deployments` + `/api/workrooms` + `/api/extensions` and any one of those degrades under load
- Traefik forwardauth middleware (`core-forwardauth`) serializes requests behind a single keycloak round-trip

### Finding #5 — Auth-gateway `401 Not Authenticated` under burst load (new in rev 1, did not reappear in rev 2 but pattern stands)

15 of 20 workers in rev 1 hit `401 Not Authenticated` on `POST /api/workrooms/{id}/enter` with valid session cookies that had already authenticated successfully on earlier calls in the same run. Did not appear in rev 2 because rev 2's workers died earlier (at Page.goto, before reaching `/enter`). Both failures are downstream of the same root cause: the platform has no concurrency budget and serializes/drops valid traffic. The 0.13.0 report's recommendation to add per-user quota stands.

### Finding #6 — Graphiti CrashLoop pattern from 0.13.0 is resolved on 0.13.1

In the 0.13.0 baseline campaign, graphiti workrooms regularly hit CrashLoopBackOff because no resource limits were set on the subchart. On 0.13.1 (`kamiwaza-extensions-graphiti` ENG-5447) the CPU/memory caps are in place and **no graphiti CrashLoops were observed in either rev-1 or rev-2 runs**. This is a real fix that landed.

### Finding #7 — Cluster has no API-level backpressure (unchanged from 0.13.0)

The platform accepted every deploy POST even after the scheduler was saturated. User-facing impact: "Initializing…" forever with no feedback, plus 100+ pods stuck Pending until an operator cleans up.

### Finding #8 — No TTL / GC on abandoned workrooms (unchanged from 0.13.0)

After the rev-1 run there were 56 abandoned KamiwazaExtension CRs from dead workrooms (kaizen-*, service-milvus-*, tool-omniparse-*, tool-graphiti-*) sitting around for ~22 hours. The "Temporary workroom" toggle in the create wizard implies an intent to auto-destroy on logout but does not actually clean these up.

### Finding #9 — Misleading run-level "COMPLETED" status (uat-bot tooling, not platform) — fixed for rev 2

The stress-tester used to report `status=COMPLETED completed=20 failed=0` even when every worker errored. The SKILL.md patch landed in marketplace PR #46 (commit `da1255b`) before rev 2; rev 2 correctly shows `status=RUNNING` while workers are stuck and a clean `status=CANCELLED` when stopped early.

## Recommended fixes (priority order, consolidated)

### 1. Reduce per-workroom pod cost — only durable fix for the cluster wedge

Largest leverage first:

- **Shared Milvus per cluster** instead of per workroom — drops 4 pods per workroom to 0 marginal. The Global Workroom already runs a shared `service-wr1-milvus-*`; extend the same pattern to user workrooms via collection-level isolation.
- **Shared Graphiti/Neo4j per cluster** with database-level isolation — drops 2 pods to 0 marginal.
- **Lazy provisioning of vectordb / graph stores** — don't deploy Milvus + Graphiti + Omniparse at workroom-create time. In both runs every workroom got the full allocation but none ingested any content. Defer until first use of the feature that needs them.
- **Consolidate Kaizen containers** — `kaizen-postgres` and `kaizen-sandbox-controller` could plausibly run as sidecars in the backend pod. Cuts kaizen from 4 → 2 pods.

(a) + (b) alone drops per-workroom cost from ~11 to ~3 pods, **lifting the single-node ceiling from 7 to ~25 concurrent workrooms** with no other change.

### 2. Investigate frontend `/workrooms` Page.goto timeout under concurrency (new — rev-2 specific)

10/20 workers timed out on `/workrooms` navigation at 60s. Worth profiling: which downstream call(s) on the workrooms route degrade under concurrent admin sessions? Forwardauth round-trip? `/api/workrooms` listing? `/api/extensions` enumeration? Add a Server-Timing header to the workrooms route handler and re-run.

### 3. Fix milvus `:2.3.0` image-tag mismatch (new — rev-2 specific)

Either (a) publish `service-milvus:2.3.0` from `kamiwaza-extensions-milvus` `release/0.13.1`, or (b) fix the workroom-manager runtime catalog to request `:develop` / `:2.2.0` / whatever actually exists. Independent of this, add a manifest-existence check to the marketplace publish pipeline.

### 4. Make extension CI publish `:release-<version>` tags

Right now only `core`, `frontend`, and `skills-library` ship a 0.13.1-aligned image. The other 7 extensions silently fall back to `:develop` on a fresh install. Workflow change: any push to `release/<X>` branch should additionally tag the image `:release-<X>`.

### 5. Investigate auth-gateway concurrency (rev-1 specific, didn't fire in rev 2 but stands)

15/20 workers in rev 1 hit `401 Not Authenticated` on `/api/workrooms/{id}/enter` with valid sessions that had already authenticated earlier in the run. Hypotheses:

- Auth-gateway has a per-session or per-user concurrency limit that drops sessions when crossed
- Keycloak token validation backpressures under burst and the gateway turns slow-responses into 401s
- Concurrent sessions for the same user (admin) are stepping on each other in workroom-binding state
- Rate-limiting middleware is misfiring on legitimate traffic

The rev-1 run's `data/runs/42b326ad147240569d065671af5d5543/events.jsonl` has exact request timing.

### 6. Workroom lifecycle / TTL — close the leak

- **Verify `is_ephemeral=true` workrooms actually destroy on session end.** 56 abandoned KX CRs after rev 1 suggests the destroy hook isn't firing reliably.
- **TTL on persistent workrooms with no activity** — auto-archive after, say, 24h idle.
- **Fail-fast on stuck deploys** — if a workroom's pods are `Pending` or `ImagePullBackOff` for > 5 min, mark the deployment FAILED, surface that in the panel, and delete the underlying Deployment objects so the scheduler stops trying.

### 7. Cluster-side backpressure

- **Reject deploy requests when scheduler is at capacity** — check recent `FailedScheduling` events or pending-pod count; return 503 with a useful message.
- **Per-user workroom quota** (admin-configurable, e.g., 5 concurrent workrooms per user).
- **Surface "your workroom is queued — cluster is at capacity"** in the UI instead of the perpetual "Initializing…" badge.

### 8. Marketplace extension-push image tag mismatch (carried forward from rev 1)

Independent of #3 above. The `kamiwaza-engineering-marketplace` push pipeline tags workroom-manager `:0.6.19-dev` when run with `STAGE=dev` (default), but GHCR only has `:0.6.19`. Same class of bug as #3; same class of fix.

## Suggested next test

Once shared Milvus + shared Graphiti are designed in, re-run this same 20-bot scenario to validate the architectural fix. The headline metric would be: how many of 20 bots reach the Kaizen UI within their 30-min timeout? **Target: ≥18/20 (allow for transient flakes), with no 401 storm, ≤30 FailedScheduling events total, no ImagePullBackOff, and the frontend `/workrooms` route returning within 5s under 20-session concurrency.**

## Caveats on this report

- Scenario does not include an agent-create step; even the workers that reached the Kaizen UI couldn't actually send messages. This is a stress-tester scenario gap, not a 0.13.1 platform issue. The original goal of "exercise the context manager via 3 conversations" remains untested on either version. The platform-layer findings here stand independently.
- Rev-2 run was cancelled at ~6 min once the failure profile was established, rather than waiting out the 30-min scenario timeout per worker. The 8 "still-running" workers at cancellation were stuck on screenshots past `07_kaizen_ui_loaded` with no progress for 90+ seconds.
- The kind node has cached `kaizen:1.8.13`, `milvus:2.3.0` (huh — actually only 2.2.0 cached, the 2.3.0 request fails), `omniparse:2.0.14`, `workroom-manager:0.6.19-dev` image layers from prior runs. Some of these tags do not exist on GHCR — see Finding #3. A fresh cluster would fail harder.
- I broke `workroom-manager` and `skills-library` extensions during rev-1 cleanup over-reach; they were restored via the UI install flow and via manual Deployment-image patch (`:0.6.19-dev` → cached layer pointer) before rev 1's 20-bot run and remain in that state for rev 2.
