# Load Test Report — 100-Bot Multi-Model Workroom-Launched Kaizen Flow

**Date:** 2026-05-26
**Run ID:** `ec889470cede47d6b235b4878b19ae8d`
**Stack:** perf-overhaul branch set + kaizen connector-overhaul (local build)
**Status:** COMPLETED. **10 of 100 bots succeeded end-to-end.**
**Verdict:** **Platform breaks at 50-concurrent on the FIRST navigation** due to a stress-tester YAML using `wait_for: networkidle` + a Keycloak login-page that drops connections under simultaneous-50 load. Once bots get past those two gates, the deploy → conversation → Hello chain works. All 10 successes clustered in workers 76, 85-92, 94 — i.e., **late-wave bots that benefited from cluster warmup**; the first 50 bots got zero successes.

## Stack under test

| Repo | Branch | Build source | Notes |
|---|---|---|---|
| `kamiwaza` | `feature/0.13.1-core-auth-perf-overhaul` | CI image `ghcr.io/.../core:pr-1807` | ForwardAuth cache, db-pool caps, auth-refresh hardening |
| `deploy` | `feature/0.13.1-deploy-perf-overhaul` | Local working tree | Auth-load harness, lazy workroom-context provisioning |
| `containers` | `feature/0.13.1-llamacpp-arm64-embedding` | Inherited via kamiwaza pr-1807 | llamacpp ARM64 embedding |
| `kamiwaza-extensions-kaizen` | `feature/0.13.1-kaizen-connector-overhaul` (`56fb212`) | Local build, all 4 images cached on kind node | Runtime-MCP discovery code path; not exercised by `workroom_kaizen_hello` |

## Models exercised (random per-bot)

| Model | Engine | Port |
|---|---|---:|
| gpt-5.2-pro | external_chat | 61124 |
| gpt-5.4 | external_chat | 61104 |
| gpt-5.4-mini | external_chat | 61121 |
| gpt-5.5 | external_chat | 61120 |

## Pre-flight (all green)

| Step | State |
|---|---|
| Pre-run cleanup | 42 leftover workrooms deleted via `DELETE /workrooms/api/admin/workrooms/{id}` (200 OK); reconciler drained 118→3 pods |
| Cluster baseline | 26% CPU / 8% memory, 3 pods in `kamiwaza-extensions` |
| Kaizen image cache | All 4 images already present in kind containerd (no cold pull) |
| Smoke (1-bot) | **COMPLETED, 39/39 steps, 239s wall** ✓ |

## Run config

| Parameter | Value |
|---|---|
| `concurrent_users` | 100 |
| `STRESS_TESTER_MAX_WORKERS` | **50** (vs prior 20) |
| `role_distribution` | `{editor: 100}` |
| `duration_seconds` | 5400 (90 min) |
| `ramp_up_seconds` | 120 |
| scenario | `workroom_kaizen_hello` |
| cluster | kind+podman, 1 node, 24 CPU / 226Gi |

## Result tally (final)

| Stage | Count | % of 100 |
|---|---:|---:|
| Workers started | 100/100 | 100% |
| Workers crashed at login (`unable to locate login inputs`) | **36** | 36% |
| Scenario step 1 (`Page.goto /workrooms` 60s timeout) | **37** | 37% |
| Scenario step 31 (`composer not found after 1200s`) | **9** | 9% |
| Scenario step 14 (`/enter 401`) | **7** | 7% |
| Scenario step 11 (workroom-list race) | 1 | 1% |
| **Hello + LLM success** | **10** | 10% |

Per-10-bot wave success:

| Workers | Login crashes | Hello+LLM success |
|---|---:|---:|
| 1-10 | 0 | **0** |
| 11-20 | 0 | **0** |
| 21-30 | 2 | **0** |
| 31-40 | 0 | **0** |
| 41-50 | 0 | **0** |
| 51-60 | **10** | 0 |
| 61-70 | 9 | 0 |
| 71-80 | 5 | **1** |
| 81-90 | 4 | **6** |
| 91-100 | 6 | **3** |

**Key pattern:** workers 1-50 all reached `/workrooms` but were strangled by `networkidle`. Workers 51-70 were strangled by Keycloak's connection-drop wave. Workers 71-100 only had a half-warm cluster but hit the highest success rate (10/30) once both bottlenecks eased.

Successful bot wall times: **333-400s (min/max), median 352s** (5:52). Slightly slower than the prior 20-concurrent runs (291s median) because the cluster was loaded.

Cluster peak: 51% CPU / 16% memory, 99 pods. Compute headroom plenty. **The bottlenecks are NOT cluster capacity.**

## Three findings, each with code reference + fix

### Finding #1 — Scenario uses `wait_for: networkidle` on `/workrooms` SPA → 60s timeout under load

This is the single biggest failure mode (**37 / 100 bots**). It's a one-line scenario YAML fix.

**Evidence (full error from event log):**

```
Page.goto: Timeout 60000ms exceeded.
Call log:
  - navigating to "https://hpe-demo-0130.westus2.cloudapp.azure.com/workrooms",
    waiting until "networkidle"
```

**Why it happens:** at 50-concurrent, the dashboard SPA on `/workrooms` fires multiple parallel `/api/*` fetches (workrooms list, extensions list, session info). Under load each takes 3-3.5s (verified live). Subsequent SPA components keep firing more fetches as data arrives. **`networkidle`** waits for "500ms of no network activity" — under sustained polling, that window never opens.

**Verified API timings under run load:**

```
$ curl -w "%{http_code} %{time_total}s\n" /api/workrooms              → 307 in 3.456s
$ curl -w "%{http_code} %{time_total}s\n" /api/extensions             → 200 in 3.627s
$ curl -w "%{http_code} %{time_total}s\n" /workrooms/api/workrooms    → 200 in 3.641s
$ curl -w "%{http_code} %{time_total}s\n" /workrooms (HTML)           → 200 in 0.803s
```

API endpoints are healthy (3-4s response). HTML serve is fast (0.8s). The bottleneck is browser-side network-idle, not server-side latency.

**Fix location:** [uat-bot/stress_tester/scenarios/builtin/workroom_kaizen_hello.yaml:11](uat-bot/stress_tester/scenarios/builtin/workroom_kaizen_hello.yaml#L11)

```yaml
# BEFORE (line 11):
  - action: navigate
    url: /workrooms
    wait_for: networkidle   # ← times out under load

# AFTER:
  - action: navigate
    url: /workrooms
    wait_for: domcontentloaded   # fires when HTML is parsed
  # Then add an explicit wait for the "Create Workroom" trigger to be visible:
  - action: js_eval
    value: |
      await page.waitForSelector('button:has-text("Create Workroom")', {timeout: 60000});
```

The `domcontentloaded` default in [browser/actions.py:246](uat-bot/stress_tester/browser/actions.py#L246) is correct; the YAML overrode it unnecessarily.

**Estimated impact:** converts **~37 of 37 wave-1 Page.goto failures** into successful navigations. Headline jumps from 10% to ~47%.

---

### Finding #2 — Keycloak login page throws `HttpClosedException` under 50-concurrent fresh sessions → bot sees blank page → "unable to locate login inputs"

**36 of 100 bots crashed at login** before even running the scenario.

**Evidence (Keycloak stderr, captured live during run):**

```
2026-05-26 22:05:43,439 ERROR [org.keycloak.services.error.KeycloakErrorHandler]
  (executor-thread-516) Uncaught server error: java.io.IOException:
  java.io.IOException: io.vertx.core.http.HttpClosedException: Connection was closed
    at io.netty.handler.timeout.IdleStateHandler.channelInactive(IdleStateHandler.java:280)

2026-05-26 22:05:43,440 ERROR [...] (executor-thread-515) Uncaught server error:
  java.io.IOException: ... HttpClosedException: Connection was closed
2026-05-26 22:05:43,440 ERROR [...] (executor-thread-517) Uncaught server error:
  java.io.IOException: ... HttpClosedException: Connection was closed
```

Three concurrent executor threads (515, 516, 517) all dropped connections simultaneously at 22:05:43 — exactly when wave 1's 50 bots all hit Keycloak login at once. The bot-side error is `unable to locate login inputs` because the login HTML never finished serving.

**Root cause:** Keycloak's default Quarkus HTTP config has `http-pool-max-threads` defaulting to ~200 but the idle-state-handler is closing connections that were taking too long to respond to client requests under contention.

**Fix locations:**

1. **Tune Keycloak HTTP config** in the chart's Keycloak deployment env or args. Check current values:
   ```bash
   kubectl -n kamiwaza get deploy keycloak -o jsonpath='{.spec.template.spec.containers[0].args}'
   ```
   Add or bump:
   ```yaml
   args:
     - --http-pool-max-threads=400
     - --http-server-enabled=true
     - --http-idle-timeout=120s
   ```
   Or via environment:
   ```yaml
   env:
     - name: KC_HTTP_POOL_MAX_THREADS
       value: "400"
     - name: KC_HTTP_IDLE_TIMEOUT
       value: "120s"
   ```
   Chart values file: [deploy/charts/kamiwaza/values.yaml](deploy/charts/kamiwaza/values.yaml) (look for `keycloak:` section) or [deploy/cluster/values/overrides.yaml](deploy/cluster/values/overrides.yaml).

2. **Bot-side mitigation** — bump the `_first_visible` 40s budget on login. File: [uat-bot/stress_tester/core/worker.py](uat-bot/stress_tester/core/worker.py) `_first_visible()` method, currently `wait_for_selector(..., timeout=5000)` per selector × 8 selectors = 40s. Bumping to 10000 (80s total) would absorb the worst-case Keycloak response. This is a workaround; the real fix is the chart change.

**Estimated impact:** Keycloak fix would convert **~36 of 36 login crashes** into successful logins. Combined with Finding #1, headline reaches ~80%.

---

### Finding #3 — Sandbox-controller readiness probe fires before agent binds — benign but log-noisy

**0 of 100 bots failed because of this**, but every sandbox in the run threw a `Warning Unhealthy` event that misleadingly looks like a bug.

**Evidence (live capture from `kaizen-sandbox-924698ea`):**

```
$ kubectl get events -n kamiwaza-sandboxes
T+0   Normal   Created    pod/kaizen-sandbox-924698ea  Created container: agent
T+0   Normal   Pulled     "host.docker.internal:5001/.../agent:1.8.13-dev" already present
T+0   Normal   Started    Started container agent
T+5s  Warning  Unhealthy  Readiness probe failed: connect: connection refused
T+10s [next probe — succeeds, pod Ready]

$ kubectl logs -n kamiwaza-sandboxes kaizen-sandbox-924698ea
[kaizen-entrypoint] Running SSL setup with sudo...
[kamiwaza-entrypoint] WARNING: Could not connect to host.docker.internal:443
            ← non-fatal, agent proceeds
22:11:26 INFO  Started server process [1]
22:11:27 INFO  Application startup complete.
22:11:27 INFO  Uvicorn running on http://0.0.0.0:8000   ← ready at T+3s
22:11:29 INFO  GET /alive 200                          ← kubelet probe (2nd attempt)
```

**Root cause:** the readiness probe is configured without `initialDelaySeconds`, so kubelet fires the first probe at T=0 — before the agent's uvicorn finishes binding port 8000.

**Fix location:** [kamiwaza-extensions-kaizen/apps/kaizenv3/packages/kaizen-workspace/kaizen/sandbox_controller/backends/kubernetes.py:450-457](kamiwaza-extensions-kaizen/apps/kaizenv3/packages/kaizen-workspace/kaizen/sandbox_controller/backends/kubernetes.py#L450-L457) and [:540-548](kamiwaza-extensions-kaizen/apps/kaizenv3/packages/kaizen-workspace/kaizen/sandbox_controller/backends/kubernetes.py#L540-L548) (two identical blocks):

```python
# BEFORE:
readiness_probe=client.V1Probe(
    http_get=client.V1HTTPGetAction(path="/alive", port=container_port),
    period_seconds=5,
    failure_threshold=60,
),

# AFTER:
readiness_probe=client.V1Probe(
    http_get=client.V1HTTPGetAction(path="/alive", port=container_port),
    initial_delay_seconds=5,   # ← agent binds in ~3s; skip first noisy probe
    period_seconds=5,
    failure_threshold=60,
),
```

**Impact:** zero behavior change (pod still has the same 5 min budget via `5s × 60 failureThreshold`); just suppresses the spurious "Readiness probe failed" event. Operator-friendly.

---

## Confirmed working at this concurrency

These are NOT problems, in case anyone reading thinks they might be:

- ✅ **Kaizen image cache** — all four images (agent 1.7GB, frontend 397MB, backend 881MB, controller 354MB) cached in kind's containerd from prior runs. New sandbox pods start with `already present on machine`, ~0s pull. **No cold-pull delay.**
- ✅ **Sandbox agent startup** — uvicorn binds `:8000` in ~3s in every observed sandbox. `/alive` returns 200 from the 2nd probe onward.
- ✅ **Sandbox-controller `_wait_for_ready` budget** — 5 min (300s) per [`_wait_for_ready(pod_name, timeout=300)`](kamiwaza-extensions-kaizen/apps/kaizenv3/packages/kaizen-workspace/kaizen/sandbox_controller/backends/kubernetes.py#L652) — plenty.
- ✅ **Cluster compute** — 24 CPU / 226Gi RAM, peak 51% / 16% during the run.
- ✅ **Local image registry + kind containerd mirror** — pushing to `host.docker.internal:5001` and the kind node pulling from `kind-registry:5000` mirror work flawlessly under load.
- ✅ **External_chat model deployments** — 4 chat models all healthy; bots successfully picked one at random and got LLM responses.
- ✅ **Kaizen connector-overhaul images functionally** — every successful bot's flow uses these images. Structural validation passes.

## What is NOT verified by this run

- **The actual connector-overhaul feature** (`Discover deployed connector runtime MCPs`). `workroom_kaizen_hello` attaches no MCP tools and uses no skills. There is a `workroom_kaizen_connector.yaml` scenario in [uat-bot/stress_tester/scenarios/builtin/](uat-bot/stress_tester/scenarios/builtin/workroom_kaizen_connector.yaml) that exercises the connector MCP discovery + tool-use code path. Recommend running that scenario (single-bot first, then small concurrency) as the next test to validate the actual feature delta.

## Reproduction (when fixes land)

```bash
# 1. Apply Finding #1 fix (one-line YAML)
sed -i 's/    wait_for: networkidle/    wait_for: domcontentloaded/' \
    uat-bot/stress_tester/scenarios/builtin/workroom_kaizen_hello.yaml

# 2. Apply Finding #2 fix (Keycloak chart) — pick the env var path
kubectl -n kamiwaza set env deploy/keycloak \
    KC_HTTP_POOL_MAX_THREADS=400 KC_HTTP_IDLE_TIMEOUT=120s

# 3. Apply Finding #3 fix in kaizen sandbox-controller source (Python edit),
#    then rebuild controller image:
cd kamiwaza-extensions-kaizen
make build TYPE=app NAME=kaizenv3
docker push host.docker.internal:5001/kamiwaza-extensions-kaizen/images/controller:1.8.13-dev

# 4. Pre-run cleanup (idempotent)
ADMIN_PW=$(kubectl -n kamiwaza get secret kamiwaza-user-admin -o jsonpath='{.data.password}' | base64 -d)
TOK=$(curl -sk -X POST "https://hpe-demo-0130.westus2.cloudapp.azure.com/realms/kamiwaza/protocol/openid-connect/token" \
    -d "client_id=kamiwaza-platform" -d "grant_type=password" -d "username=admin" --data-urlencode "password=$ADMIN_PW" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
curl -sk -H "Authorization: Bearer $TOK" "https://hpe-demo-0130.westus2.cloudapp.azure.com/workrooms/api/admin/workrooms" \
    | python3 -c "import json,sys; [print(w['id']) for w in json.load(sys.stdin) if not w['id'].startswith('ffffffff')]" \
    | xargs -P 8 -I{} curl -sk -X DELETE -H "Authorization: Bearer $TOK" \
        "https://hpe-demo-0130.westus2.cloudapp.azure.com/workrooms/api/admin/workrooms/{}"

# 5. Smoke + 100-bot launch (same as this run)
```

## Caveats

- **`STRESS_TESTER_MAX_WORKERS=50` means 100 bots in 2 waves of 50** — not 100 simultaneous. The platform never saw more than 50 simultaneous browser sessions driving traffic.
- **The 36 login-crash bots are client-side process contention as much as Keycloak.** Spawning 50 fresh headless Chromium instances on one host competes for CPU and TCP sockets too. Distributing the load test across multiple hosts would help isolate which side is at fault.
- **Cluster is on a single dev kind node.** Production-shape testing requires a multi-node cluster with proper load balancing.
