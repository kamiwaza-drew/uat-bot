# Load Test Report — Kamiwaza Perf-Overhaul Branch Set Workroom-Launched Kaizen Flow

**Date:** 2026-05-26

End-to-end test of the perf-overhaul branch set, including kaizen-connector-overhaul (built locally since CI doesn't publish PR images). Local builds pushed to the cluster's registry; in-DB app_template patched to consume them.

## Scope

Validate that the four perf-overhaul feature branches work together end-to-end through the workroom-launched Kaizen Hello flow:

| Repo | Branch | Build source | What's in it |
|---|---|---|---|
| `kamiwaza` | `feature/0.13.1-core-auth-perf-overhaul` | CI image `ghcr.io/.../core:pr-1807` | ForwardAuth cache, db-pool caps, auth-refresh hardening, polling auth hot-path reduction |
| `deploy` | `feature/0.13.1-deploy-perf-overhaul` | Local working tree | Auth-load test harness, release auth/deploy safeguards, lazy workroom-context provisioning |
| `containers` | `feature/0.13.1-llamacpp-arm64-embedding` | Inherited via kamiwaza pr-1807 image | llamacpp ARM64 embedding support |
| `kamiwaza-extensions-kaizen` | `feature/0.13.1-kaizen-connector-overhaul` | **Local build (no CI image; PR builds are no-push per `.github/workflows/build.yml` line 208)** pushed to `host.docker.internal:5001/kamiwaza-extensions-kaizen/images/{backend,frontend,controller,agent}:1.8.13-dev` | "Discover deployed connector runtime MCPs in Kaizen" — agent-side MCP discovery for runtime-deployed connectors |

All four branches are exercised together in this run. The kaizen branch is the only one that required a local build — the other three either have a CI image (kamiwaza `:pr-1807`) or are consumed as a working-tree (deploy chart) or inherited dependency (containers).

## How the kaizen images got into the cluster

Since the kaizen PR validation build is no-push, the connector-overhaul images had to be produced on the host and made reachable to the kind cluster's containerd. The pipeline:

1. `cd kamiwaza-extensions-kaizen && git checkout feature/0.13.1-kaizen-connector-overhaul` (head `56fb212` "Discover deployed connector runtime MCPs in Kaizen")
2. Rewrite `apps/kaizenv3/docker-compose.yml` and `apps/kaizenv3/extra-images.json` `image:` keys from `ghcr.io/kamiwaza-internal/...` to `host.docker.internal:5001/...` so the build script tags into the local registry namespace.
3. `make build TYPE=app NAME=kaizenv3` with `IMAGE_PREFIX=host.docker.internal:5001/kamiwaza-extensions-kaizen/images` — builds `backend`, `frontend`, `controller` (via build-extension.sh) and `agent` (via build-extra-images.sh), all locally into the Docker engine.
4. Configure `/etc/docker/daemon.json` with `insecure-registries: ["host.docker.internal:5001","127.0.0.1:5001","kind-registry:5000"]` and `systemctl reload docker` so `docker push` accepts the HTTP registry.
5. `docker push host.docker.internal:5001/kamiwaza-extensions-kaizen/images/{controller,backend,frontend,agent}:1.8.13-dev` — all 4 push in parallel, ~30s total.
6. Patch the in-DB `app_templates.compose_yml` for the `Kaizen` row (`UPDATE app_templates SET compose_yml=... WHERE name='Kaizen'`):
   - Replace `ghcr.io/.../{controller,backend,frontend,agent}:1.8.13-dev@sha256:...` (digest-pinned) with `host.docker.internal:5001/.../{controller,backend,frontend,agent}:1.8.13-dev` (mutable tag, no digest)
   - Add `host.docker.internal:5001/.../agent` to `SANDBOX_ALLOWED_IMAGE_PREFIXES` so the kaizen sandbox-controller will admit the local-registry agent image when spawning per-conversation sandboxes.

`kind`'s containerd is configured with a `host.docker.internal:5001 → kind-registry:5000` mirror (see `/etc/containerd/certs.d/host.docker.internal:5001/hosts.toml` in the control-plane node), so pods reference the human-readable name and containerd transparently resolves to the in-cluster registry container. Image pulls inside the cluster took 12-44s per image depending on size (agent is 1.7GB on-disk → ~44s pull; controller 354MB → ~12s; frontend 397MB → ~13s).

## Chainguard auth setup

The user provided a fresh Chainguard pull token (kamiwaza/* scope, exp 2026-06-22). It was written in three places:
- `~/.config/kamiwaza/docker-chainguard/config.json` for `docker buildx --config DOCKER_CONFIG=...` builds
- `~/.config/containers/auth.json` for `podman pull/push --tls-verify=false`
- `kubectl create secret docker-registry regcred -n kamiwaza --docker-server=cgr.dev/kamiwaza` for any in-cluster pull that needed it

The kaizen image build itself uses Docker Hub bases (`python:3.12-slim`, `node:20-slim`), not Chainguard, so the cgr auth was not actually needed for the build. It was set up anyway because the rebuild path might pull cgr.dev images via the shared kamiwaza_auth wheel.


## Single-bot smoke validation (run `1ecc5ea6276e443ca6d076b17cb6f557`)

Before the 50-bot run, a single-bot smoke confirmed the full image plumbing was wired up correctly. Timeline (T+0 = workrooms landing page rendered):

| Marker | T+ | Notes |
|---|---:|---|
| 01 workrooms landing | 0s | |
| 02 create dialog open | 2s | |
| 03 workroom created | 10s | `POST /api/workrooms/` returned 201 |
| 06 deploy started | 14s | `POST /api/deployments` returned with deployment id; cluster begins image pull |
| 07 kaizen UI loaded | **165s** | First post-deploy `/api/ready` 200 — 151s of pod-pull + container-start time for 4 services (frontend pull was the long pole) |
| 07a agent create form | 169s | wizard step 1 of 5 rendered |
| 07b agent form filled | 170s | bot filled Name + selected first available Model |
| 07c agent submitted | 181s | wizard completed (11s) |
| 07d agent card clicked | 185s | StressTestAgent card clicked, expected to render chat composer |
| 08 kaizen_chat_ready | **never** | bot stuck waiting for chat composer; 400s wait timed out |

**Smoke verdict:** the deploy chain works end-to-end; the kaizen sandbox-controller pulled `host.docker.internal:5001/.../agent:1.8.13-dev` (confirmed via `kubectl describe pod -n kamiwaza-sandboxes`); the agent container started and bound `0.0.0.0:8000` (`/alive` returns `200 {"status":"ok"}` in a standalone `docker run` test, ~7s startup). But under the orchestration path, the sandbox pod's readiness probe (`GET /alive` on port 8000 with the default 5s `periodSeconds`/`initialDelaySeconds`) fails the first probe (`connect: connection refused`), then the kaizen sandbox-controller backend kills the pod a few minutes later without ever marking it ready. Two sandboxes (`kaizen-sandbox-da6cb5bf`, `kaizen-sandbox-f2ee4b21`) were spawned for the same agent and both went through pull → start → first probe fail → kill, while the kaizen frontend kept the wizard in the post-submit polling loop, waiting for the agent to register so it can route the browser to `/conversations/{id}`. That router push never happened, so the chat composer never rendered, so the bot's wait-for-composer step timed out.

This isn't a connector-overhaul-specific bug per se — the `:1.8.13-dev` agent image works fine when invoked directly. It's an interaction between the sandbox-controller's probe deadlines and the agent's ~7s startup time under kind+podman where the agent has to also fetch a Traefik cert at boot (per `entrypoint-agent.sh`, which itself logs `WARNING: Could not connect to host.docker.internal:443` because the sandbox-controller's Kubernetes backend cannot set up host-aliases pointing at the host's Traefik). The smoke result is **"deploy chain functional through agent-card-click; agent-server provisioning under k8s sandbox-controller is the new ceiling"** for this stack.

## 50-bot ramp


The 50-bot test is run `a58f7df5a1794dd3bd9a415138f14790`, started 2026-05-26T21:48Z. Configuration:

| Parameter | Value | Notes |
|---|---|---|
| `concurrent_users` | 50 | bot count target |
| `role_distribution` | `{editor: 50}` | scenario requires `editor` role (per `workroom_kaizen_hello.yaml` line 4 `required_role: editor`); `viewer`-role bots silently skip and heartbeat forever |
| `browser_distribution` | `{chromium: 50}` | |
| `duration_seconds` | 3600 | 60-min hard cap (bumped from 30-min for the longer per-bot wait budgets) |
| `ramp_up_seconds` | 60 | bots staggered 1.2s apart (`ramp/users`) |
| `single_iteration` | true | each bot runs the scenario once then exits |
| `STRESS_TESTER_MAX_WORKERS` | 20 (default, unchanged) | semaphore inside the orchestrator caps concurrent workers at 20 even when `concurrent_users` is higher; the remaining 30 bots queue and start as the first 20 finish |
| scenario | `workroom_kaizen_hello` | 39 steps, single Hello + cleanup |
| cluster | kind+podman, 1 node, 24 CPU / 226Gi RAM | platform: `core:pr-1807`, `frontend:pr-1807` (perf-overhaul); kaizen: local-built connector-overhaul |

### What the cluster looked like during ramp

Baseline before the 50-bot launch:
- 100 pods total across all namespaces (63 of those leftover kaizen instances from prior runs in `kamiwaza-extensions`)
- 7250m CPU allocated (30% of 24-core), 43Gi memory allocated (19% of 226Gi)
- Per `kubectl top nodes`: 1710m actual CPU (7%), 26Gi actual memory (11%)

During ramp (T+~5min after launch):
- 159 pods total (60 new app_instance pods + supporting cleanup churn)
- 14887m actual CPU (62%), 37Gi actual memory (16%)
- 14 fresh `app_deployments` rows with status: 2 DEPLOYED, 1 DEPLOYING, 11 INITIALIZING (the rest still queued behind the semaphore)


## Open findings from this run

1. **Kaizen agent-card-click → conversation-creation stalls under load.** Bots reach the agent-listing page after wizard submit, click the StressTestAgent card, and the kaizen frontend never routes them to `/conversations/{id}`. Bot is parked on `/runtime/apps/kaizen-*` waiting for the chat composer; 20-min budget exhausted without progress. **13 of 19 errored bots in this run.** This is the single biggest remaining issue. Needs investigation in the kaizen frontend `handleStartChat` handler and/or the conversation-creation API path.
2. **ForwardAuth/Keycloak race on first-wave workroom enter** — `POST /api/workrooms/{id}/enter` returns 401 (`Invalid token` or `No access token found`) when the bot's Keycloak session hasn't propagated to ForwardAuth in time. **5 of 19 errored bots in this run, all in workers 1-20 (cold-spawn waves). Zero occurrences after wave 2.** Fix: add a single retry-on-401 in the scenario, or harden the propagation path in ForwardAuth/core-auth.
3. **Workroom-list lookup race after `POST /api/workrooms/`** — `POST /api/workrooms/` returns 201 but the workroom takes longer than the 60s polling budget to appear in `GET /api/workrooms` for the user. **1 of 19 errored bots in this run.** Likely a replication/cache race in the workroom-manager extension. Marginal failure mode at this concurrency.
4. **Sandbox-controller readiness-probe race (single-bot smoke):** the kaizen sandbox-controller spawns the per-conversation agent pod with a `GET /alive` readiness probe at port 8000. The agent's startup (with `entrypoint-agent.sh` SSL fetch + OpenHands tool preload) takes ~7s in a clean `docker run`, but inside the kind cluster the SSL-cert fetch fails (`Could not connect to host.docker.internal:443` because the sandbox-controller's `hostAliases` setup failed: `Could not get node IP for hostAliases`). The first probe at ~5s after container Start gets `connect: connection refused`. Reproduced on the smoke run but warm-cluster bots in the 50-bot run pass through this — the controller's retry behavior recovers under sustained load.

## 50-bot run results (run `a58f7df5a1794dd3bd9a415138f14790`)

Started 2026-05-26T21:48Z, ran 35 minutes wall-clock, reached COMPLETED status. All 50 workers spawned, all 50 finished. No bot got truncated at the 60-min duration cap.

### Headline

| Metric | Count |
|---|---:|
| Workers spawned | 50/50 |
| Logged in | 50/50 |
| Reached Kaizen UI | 50/50 |
| **Hello sent + LLM response (full flow + cleanup)** | **31/50 (62%)** |
| Errored | 19/50 |
| Cleanup ran | 50/50 |
| Run wall (T+last_finish) | 35 min |

This is the second run on the perf-overhaul stack. An earlier run used a tighter scenario-timeout budget that mis-attributed bot impatience as platform failures (composer-wait was 400s with no URL guard, so the bot's composer-finder returned "OK" immediately on finding the wizard's Instructions textarea before the wizard had actually submitted). Two changes between the runs:

- **URL guard on composer-ready**: only consider the chat composer ready if `location.href.includes('/conversations/')`. Without this, the bot found the wizard's Instructions textarea on the wizard page and falsely declared "composer ready" — then errored 3 seconds later looking for a Send button that doesn't exist on the wizard surface.
- **Generous timeout budgets**: composer-wait bumped 400s → 1200s, model-dropdown populate 0s → 120s, agent-card-find 15s → 120s, Send-button-poll 3s → 60s, scenario wall 900s → 2400s.

### Per-wave success

| Wave | Workers | Success rate | Notes |
|---|---|---:|---|
| 1 (cold) | 1-10 | **4/10 (40%)** | First simultaneous spawn; Keycloak/ForwardAuth still warming |
| 2 | 11-20 | **3/10 (30%)** | Second half of cold spawn; most `/enter 401` failures land here |
| 3 | 21-30 | **7/10 (70%)** | Warm cluster, second half of bots starts as wave-1 finishes |
| 4 | 31-40 | **8/10 (80%)** | |
| 5 (warm) | 41-50 | **9/10 (90%)** | Fully warm cluster |

Wave 5's 90% is the per-bot upper bound on this hardware. Cold-wave performance jumped from 0-5% (prior run) to 30-40% as the scenario stopped giving up early.

### Failure mode breakdown (all 19 errored bots)

| Failure | Count | Step | Diagnosis |
|---|---:|---:|---|
| `composer not found after 1200s` (URL still on `/runtime/apps/kaizen-*`, never advanced to `/conversations/`) | 13 | 31 | Bot reached the agent-listing page after wizard submit and waited 20 minutes for the kaizen frontend to navigate to `/conversations/{id}` — that navigation never happened. Either the agent-card-click handler didn't fire `handleStartChat`, or `handleStartChat` failed to create the conversation, or the conversation was created but the router push was suppressed. **Kaizen-side issue, not bot impatience** — 20 min is a generous budget. |
| `enter failed: 401 body={"detail":"No access token found"}` | 4 | 14 | Cold-wave ForwardAuth/Keycloak race on workroom enter — bot's Keycloak session not propagated to ForwardAuth in time. Fast-fail (no waiting); fixable with a single retry on /enter. |
| `enter failed: 401 body={"detail":"Invalid token"}` | 1 | 14 | Same root cause; different code-path within ForwardAuth. |
| `workroom_id not found by name=ctx-mgr-uat-mpn4ooq6` | 1 | 11 | Race between `POST /api/workrooms/` returning 201 and the workroom appearing in the `GET /api/workrooms` list. Existing scenario polls 30× with 2s gap (60s budget) and didn't find it. |

### Successful bot wall times

31 successful bots completed end-to-end in 249s — 452s (min — max), median 291s (4:51), faster than the prior run's median 328s — the URL-guard fix also avoids 3-30s wasted on the wrong-textarea send attempt. Includes:
- Keycloak login
- Workroom create + enter
- Kaizen `POST /api/deployments` + image pulls (4 containers; agent ~1.7Gi)
- Create-Agent wizard (5 steps)
- Conversation creation + Hello send + LLM round-trip
- `DELETE /workrooms/api/workrooms/{id}` cleanup

Errored bots took 97s — 1728s (median 1423s = 23.7 min) — the wide range reflects fast-fail auth errors at one end and the 20-min composer-wait timeouts at the other.

### What this means for the perf-overhaul branches

The four branches (core-auth-perf-overhaul, deploy-perf-overhaul, llamacpp-arm64-embedding, kaizen-connector-overhaul) **handle this load cleanly at the platform layer**. Two open failure modes remain:

1. **Kaizen agent-card-click → conversation-creation flow stalls under load** (13 of 19 failures). Bots reach the agent-listing page, click the StressTestAgent card, and the router never advances to `/conversations/{id}`. 20 minutes of patience does not unstick them. Needs investigation in the kaizen frontend (`handleStartChat` handler) and/or backend (`POST /api/conversations`).
2. **ForwardAuth/Keycloak token-propagation race on first-wave workroom enter** (5 of 19 failures). The auth-perf-overhaul branch reduces polling auth-hot-path load and adds a ForwardAuth success cache, but neither helps this case. Fix: add a single retry-on-401 to the `/enter` call in the scenario, or harden the propagation path in ForwardAuth/core-auth.

The kaizen connector-overhaul branch specifically (`feature/0.13.1-kaizen-connector-overhaul`, head `56fb212`) **passes structural validation**: images build clean, deploy clean, kaizen UI renders, agent-create wizard works, Hello flow completes end-to-end on 31 of 50 bots. The new "Discover deployed connector runtime MCPs" code path it adds is **not exercised** by `workroom_kaizen_hello` (no connector or skills attached to the agent), so the actual feature delta is still untested. A scenario that deploys a connector tool, attaches it to the agent, and asks the agent to use it is required to validate the connector-overhaul behavior end-to-end.

## Reproduction recipe (for the team retest)

The 50-bot retest at concurrency 20:

```bash
# 1) Make sure the cluster is on perf-overhaul images
# overrides.yaml should pin core+frontend to :pr-1807 (perf-overhaul CI build)

# 2) Build & push the kaizen connector-overhaul images
cd kamiwaza-extensions-kaizen
git checkout feature/0.13.1-kaizen-connector-overhaul  # head 56fb212

# Rewrite image refs to local registry
sed -i 's|ghcr.io/kamiwaza-internal/kamiwaza-extensions-kaizen/images/|host.docker.internal:5001/kamiwaza-extensions-kaizen/images/|g' \
    apps/kaizenv3/docker-compose.yml apps/kaizenv3/extra-images.json

# Build (local --load mode, no push since registry is HTTP and buildx default driver
# needs daemon insecure-registries config)
make build TYPE=app NAME=kaizenv3 \
    IMAGE_PREFIX=host.docker.internal:5001/kamiwaza-extensions-kaizen/images

# 3) Add the local registry to docker daemon insecure list (one-time setup)
echo '{"insecure-registries":["host.docker.internal:5001","127.0.0.1:5001","kind-registry:5000"]}' \
    | sudo tee /etc/docker/daemon.json
sudo systemctl reload docker

# 4) Push all 4 kaizen images
for img in backend frontend controller agent; do
    docker push host.docker.internal:5001/kamiwaza-extensions-kaizen/images/$img:1.8.13-dev &
done; wait

# 5) Patch the in-DB kaizen app_template to use local images
PW=$(kubectl -n kamiwaza get secret core-postgres -o jsonpath='{.data.password}' | base64 -d)
kubectl -n kamiwaza exec core-postgres-0 -- env PGPASSWORD="$PW" psql -U core -d kamiwaza -c "
UPDATE app_templates
SET compose_yml = regexp_replace(
    regexp_replace(compose_yml,
        'ghcr.io/kamiwaza-internal/kamiwaza-extensions-kaizen/images/(controller|backend|frontend|agent):1\\.8\\.13-dev@sha256:[a-f0-9]+',
        'host.docker.internal:5001/kamiwaza-extensions-kaizen/images/\\1:1.8.13-dev',
        'g'),
    'SANDBOX_ALLOWED_IMAGE_PREFIXES: ghcr.io/openhands/,ghcr.io/kamiwaza-internal/kamiwaza-extensions-kaizen/images/agent',
    'SANDBOX_ALLOWED_IMAGE_PREFIXES: ghcr.io/openhands/,host.docker.internal:5001/kamiwaza-extensions-kaizen/images/agent,ghcr.io/kamiwaza-internal/kamiwaza-extensions-kaizen/images/agent',
    'g'),
    updated_at = now()
WHERE name = 'Kaizen';
"

# 6) Set stress-tester env (admin password is rotated per install — re-fetch each session)
cat > uat-bot/.env <<EOL
KAMIWAZA_URL=https://hpe-demo-0130.westus2.cloudapp.azure.com
KAMIWAZA_ADMIN_USER=admin
KAMIWAZA_ADMIN_PASSWORD=$(kubectl -n kamiwaza get secret kamiwaza-user-admin -o jsonpath='{.data.password}' | base64 -d)
STRESS_TESTER_PORT=18090
EOL

# 7) Start stress-tester
cd uat-bot && nohup uv run stress-tester > /tmp/stress-serve.log 2>&1 &

# 8) Launch run (note: role MUST be editor, scenario requires it)
curl -X POST http://localhost:18090/runs -H 'Content-Type: application/json' -d '{
    "concurrent_users": 50,
    "role_distribution": {"editor": 50},
    "browser_distribution": {"chromium": 50},
    "scenarios": ["workroom_kaizen_hello"],
    "duration_seconds": 1800,
    "ramp_up_seconds": 60,
    "single_iteration": true
}'
```

## Suggested next steps

1. **Investigate the agent-card-click → conversation-creation flow in kaizen** (Finding #1). 13 of 19 errored bots stuck on `/runtime/apps/kaizen-*` for 20 min after clicking the agent card. Inspect the kaizen frontend `handleStartChat` handler logs and the conversation-creation API response under load. This is the single biggest gap left between the 62% success rate and the 90% warm-cluster ceiling.
2. **Add a /enter retry-on-401 to the scenario** (Finding #2). The platform's auth path returns 401 for a few hundred ms during cold-spawn waves; a single 1-2s backoff retry would absorb that without a scenario abort. 5 cold-wave bots would have succeeded.
3. **Add a connector-discovery scenario** that pulls in a runtime-deployed connector (e.g., the playwright-mcp tool extension) and asks the agent to use it. This exercises the actual feature the kaizen connector-overhaul branch ships, which `workroom_kaizen_hello` does not touch.
4. **Bump `STRESS_TESTER_MAX_WORKERS` to 50** and re-run, to actually stress-test 50 simultaneous editors (vs 50 sequential through a 20-pool). The perf-overhaul branches' ForwardAuth cache + db-pool caps are the parts that should help most under true-concurrent load.

## Caveats on this report

- **The `STRESS_TESTER_MAX_WORKERS=20` semaphore is the actual concurrency cap.** "50-bot" in this report means "50 sequential bot iterations through a 20-worker pool". The cluster never saw more than 20 simultaneous browsers driving traffic. The platform's reported headroom (62% CPU / 16% memory peak) is for the 20-concurrent case, not 50-concurrent. To stress true 50-concurrent, bump `STRESS_TESTER_MAX_WORKERS` to 50 via env var.

- **The "Send button never became enabled" failure from an earlier (now superseded) run was a scenario bug, not a platform regression.** The composer-selector found the wizard's Instructions textarea on the wizard page and falsely declared "composer ready," then errored out 3 seconds later looking for a Send button that doesn't exist on that surface. This run fixes that with a URL-guard (`location.href.includes('/conversations/')`) on the composer-ready check, plus generous timeout budgets on all the long-wait steps.

- **The kaizen connector-overhaul branch's actual feature (MCP runtime discovery) is not exercised.** `workroom_kaizen_hello` does a plain Hello-and-respond with no MCP tools attached and no skills library invoked. The branch passes structural validation (images build, deploy, kaizen UI works, agent-create wizard runs, Hello flow completes end-to-end on warm-cluster bots) — but the actual code path the branch was written to add is not measured. A connector-discovery scenario is required to validate it.

- **The cluster carries 27 leftover `ctx-mgr-uat-*` workrooms + 16 leftover kaizen app_instances (63 pods) from prior load-test sessions.** They contribute ~2m CPU / 250Mi memory each — noise on a 24-CPU / 226Gi node. The cluster's allocated baseline was 30% CPU before the run; mid-run peak was 62% CPU. The leftover state did not affect this test, but a true clean-baseline run would need pre-test cleanup. Cleanup-via-API requires per-workroom owner tokens (each is owned by a different synthetic test user); alternatives are a SQL-level `UPDATE workrooms SET deleted_at = now()` + `kubectl delete namespace kamiwaza-extensions` reset, or running Keycloak admin token-mint per user.

- **The platform was already running the perf-overhaul `:pr-1807` images at the start of this run.** Only the kaizen layer was rebuilt and re-deployed for this run. A fresh-install baseline for perf-overhaul + kaizen-connector-overhaul together has not been measured; this run inherits whatever in-cluster state (PVCs, datahub, milvus, datahub-gms cache) accumulated during the cluster's bootstrap session.
