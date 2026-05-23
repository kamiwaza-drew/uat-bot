# Load Test Report — Kamiwaza 0.13.0 Workroom-Launched Kaizen Flow

**Date:** 2026-05-23
**Target build:** Kamiwaza `release/0.13.0` branch, `:develop` core image
**Host:** `kamiwaza-dev-control-plane` — single-node kind+podman cluster on `hpe-demo-0130.westus2.cloudapp.azure.com`
**Driver:** `uat-bot` stress-tester, scenario `workroom_kaizen_ctx` (workroom create → kaizen launch → 3 conversations testing context manager)
**Campaign:** ~20 iterations over ~6 hours, single concurrent user per run

## Executive summary

0.13.0 is **not stable under repeated workroom-creation workloads** on a single-node demo cluster. After ~7 workroom creates the cluster saturates its pod budget, and from then on every new deploy is silently accepted but never schedules. There is no backpressure, no timeout, no error surfaced to the user, and no garbage collection of abandoned workrooms — so the only path to recovery is operator intervention.

Independently, the Graphiti/Neo4j subchart ships with no resource limits and ends up in `CrashLoopBackOff` on long-lived workrooms.

These are architectural issues, not bugs in any one feature. They will reproduce on any small demo cluster and likely surface for early customers running parallel demos.

## Methodology

Each iteration of `workroom_kaizen_ctx`:

1. Logs in (admin during the validated runs)
2. Creates a fresh workroom via the wizard (`POST /api/workrooms/`)
3. Triggers Kaizen deploy (`POST /workrooms/api/deployments`)
4. Polls the deployment URL until the Traefik IngressRoute serves something other than the Kamiwaza shell
5. Binds session to the workroom and navigates to `/runtime/apps/{deployment_name}/`
6. Sends three context-stressing conversation patterns

No teardown step — this mirrors a real user who creates workrooms, walks away, and never deletes them. The campaign accumulated state across all iterations.

## Observed cluster state at end of campaign

| Metric | Value | Notes |
|---|---:|---|
| Kubelet `max-pods` | 110 | kind default, hard cap |
| Pods currently scheduled | 110 | **at the limit** |
| Pods in `Pending` | 177 | stuck in scheduling queue, growing |
| Pods in `CrashLoopBackOff` | 10 | almost entirely graphiti + neo4j |
| Pods in `ImagePullBackOff` / `ErrImagePull` | 7 | image-registry transient issues |
| Accumulated `kaizen-*` Deployments | 96 | |
| Accumulated `service-milvus-*` Deployments | 63 | |
| Accumulated `service-graphiti-*` Deployments | 44 | |
| Node CPU requests | 20.1 / 24 cores (83%) | |
| Node CPU limits | 364% overcommit | best-effort under contention |
| Node memory requests | 53 GiB / 220 GiB (24%) | comfortable |
| Node memory limits | 91% | one OOM-spike from breaching |

## Per-workroom cost

Each new workroom provisions:

| Component | Pods |
|---|---:|
| kaizen (backend + frontend + postgres + sandbox-controller) | 4 |
| service-milvus (etcd + seaweedfs + standalone + init job) | 4 |
| service-graphiti (graphiti + neo4j) | 2 |
| tool-omniparse | 1–2 |
| **Total per workroom** | **~11** |

The cluster's fixed-overhead pods (`core-ray`, `core-scheduler`, `traefik`, `keycloak`, `datahub-*`, `frontend`, etc.) consume ~30 pods. That leaves ~80 pods for user workrooms → **theoretical ceiling ≈ 7 concurrent workrooms** before the cluster saturates.

## Failure mode

Once the cluster hits 110 pods, new deploys exhibit the following progression:

1. `POST /api/workrooms/` returns 201 — workroom row created in postgres.
2. `POST /workrooms/api/deployments` returns 200 with a deployment id and access_url — the launcher accepts the work.
3. Kubernetes creates the Deployment objects.
4. The kubelet refuses to schedule new pods:
   ```
   FailedScheduling: "0/1 nodes are available: 1 Too many pods.
   preemption: 0/1 nodes are available: 1 No preemption victims found"
   ```
5. **No timeout fires.** Pods sit in `Pending` indefinitely.
6. **No error surfaces to the user.** The workroom panel keeps showing "Initializing…" forever.
7. **No cleanup occurs.** A user who walks away leaves their pods queued, occupying scheduler slots from later users.

In our campaign there were Pending pods over 3 hours old at the end of the test — those represent users (or test runs) who tried to create a workroom, got no error, eventually closed the browser tab, and left the cluster permanently more saturated.

## Stress-tester run outcomes

| Status | Count | Notes |
|---|---:|---|
| API-reported `COMPLETED` | 20/20 | misleading — workers exit cleanly even on scenario errors |
| Reached a working Kaizen chat input | **0/20** | none of the iterations exercised an actual conversation |
| Failed at scenario logic / selectors | 6 | scenario maturation cost |
| Wedged for ≥ 10 min waiting on pods that never scheduled | **12** | the core stability finding |

Notably, the stress-tester API itself reported every run as `COMPLETED` because the bot worker process exited 0 — a UX bug in stress-tester (worth its own ticket).

## Secondary finding: Graphiti / Neo4j CrashLoop

Among the workrooms whose pods *did* schedule (early in the test, before saturation), the graphiti subchart ships **without `resources.requests` or `resources.limits`**. Multiple pods accumulated 70+ restarts with `Exit Code 128` (`StartError`), consistent with Neo4j OOM-killing itself during startup heap allocation. This is a separate stability problem orthogonal to pod-budget exhaustion, but it compounds the symptoms because crashed pods still occupy a scheduler slot.

## What this means for 0.13.0

The architecture as currently configured has:

- **No backpressure** — API accepts deploys the cluster can't fulfill
- **No quota** — a single user can monopolize the cluster's pod budget
- **No lifecycle** — abandoned workrooms persist forever
- **Per-workroom cost too high** — ~11 pods means a node can hold ~7 workrooms regardless of how much CPU/memory headroom is available (we used <25% of node memory at saturation)
- **Subchart drift** — graphiti/neo4j ship without resource limits

A QA team or sales demo running parallel workroom creation will wedge a single-node cluster within minutes, with no error signal pointing at the actual cause. Existing customers running on the standard kind topology will hit this on the first busy day.

## Recommended fixes (priority order)

### 1. Reduce per-workroom pod cost — the only durable fix

Per-workroom pod count is the architectural ceiling. Raising `max-pods` just postpones it.

Concrete options worth designing for 0.13.0+:

- **Shared Milvus per cluster** (4 pods → 0 marginal). The Global Workroom already runs a shared `service-wr1-milvus-*` instance — the same pattern can apply to user workrooms via collection-level isolation rather than instance-level.
- **Shared Graphiti/Neo4j per cluster** with database-level isolation (2 pods → 0 marginal).
- **Lazy provisioning of vectordb / graph stores** — don't deploy Milvus + Graphiti + Omniparse at workroom-create time. Most workrooms in the campaign data never received any ingested content; they got the full pod allocation anyway. Deploy these on first use of the feature that needs them.
- **Consolidate Kaizen containers** — `kaizen-postgres` and `kaizen-sandbox-controller` could plausibly run as sidecars in the backend pod instead of separate Deployments. That moves kaizen from 4 → 2 pods.

Just (a) shared Milvus + (b) shared Graphiti drops per-workroom cost from ~11 to **~3 pods**, raising the cluster ceiling from 7 to ~25 workrooms with no other change.

### 2. Workroom lifecycle / TTL — close the leak

The create wizard already exposes a "Temporary workroom" toggle ("Destroyed on logout — for field/denied-area use"), implying intent to auto-destroy. Two things:

- **Verify `is_ephemeral=true` workrooms actually destroy on session end.** The 3-hour-old Pending workrooms in our test data suggest the destroy hook isn't firing reliably, or sessions are timing out without triggering it.
- **TTL on persistent workrooms with no activity.** A workroom whose Kaizen has 0 sessions and 0 ingested data for N hours is dead weight. Auto-archive (with operator-configurable threshold) after, say, 24h idle.
- **Fail-fast on stuck deploys.** If a workroom's pods are `Pending` for > 5 min, mark the deployment FAILED, surface that in the panel, and delete the underlying Deployment objects so the scheduler stops trying.

### 3. Cluster-side backpressure

Today the API will happily accept `POST /api/deployments` even when the cluster cannot schedule the result. The user sees "Initializing…" indefinitely.

- **Reject deploy requests when scheduler is at capacity** — check recent `FailedScheduling` events or pending-pod count; return 503 with a message identifying the cause.
- **Per-user workroom quota** (admin-configurable, e.g., 5 concurrent workrooms per user).
- **Surface "your workroom is queued — cluster is at capacity"** in the UI panel instead of the perpetual "Initializing…" badge.

### 4. Graphiti / Neo4j resource limits

The graphiti subchart Deployments currently have empty `resources.requests` and `resources.limits`. Set sane defaults in the chart:

- Neo4j: `requests.memory: 2Gi`, `limits.memory: 4Gi`, plus the corresponding `NEO4J_dbms_memory_heap_initial__size` / `_max__size` env so the JVM heap is bounded.
- Graphiti: `requests.memory: 512Mi`, `limits.memory: 1Gi`.

This won't fix the crash entirely if there's a deeper bootstrap bug, but it will stop the OOM-loop pattern and give a clean failure signal when something else is wrong.

### 5. Raise kubelet `max-pods` (buffer, not a fix)

After (1)–(3) are in place, raising the kind kubelet's `max-pods` from 110 to e.g. 300 buys headroom for spikes:

```yaml
# kind cluster config
nodes:
  - role: control-plane
    kubeletExtraArgs:
      max-pods: "300"
```

Requires recreating the node — kind doesn't hot-reconfigure kubelet. Combined with shared Milvus + Graphiti from (1), this puts practical ceiling at ~100 concurrent workrooms per single-node demo cluster.

## Bottom line

0.13.0 ships with a per-workroom pod cost that doesn't scale, no protection against runaway accumulation, and a subchart that crashes itself under sustained load. The pod-budget exhaustion is reproducible in under an hour by a single user creating workrooms in a loop. Items (1) + (2) + (3) together are the real shape of the fix — anything short of those leaves the platform one busy demo day away from the same wedge.
