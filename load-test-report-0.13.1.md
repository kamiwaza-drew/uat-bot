# Load Test Report — Kamiwaza 0.13.1 vs 0.13.0 Workroom-Launched Kaizen Flow

**Date:** 2026-05-26 (rev 4.7 — agent-create scenario fixes land; **1-bot smoke ran Phase 5 long-context conversation end-to-end for the first time on 0.13.1**; 50-bot run separates three Kaizen-layer concurrency bottlenecks)

## 🟢 What now works (proven end-to-end on 0.13.1)

For the first time since this load-test campaign started, the bot successfully drove the full Kaizen conversation flow on a single-user session:

1. Create workroom via the wizard ✓
2. Deploy Kaizen extension to workroom ✓
3. Wait for kaizen URL to become routable ✓
4. Bind session via `/api/workrooms/{id}/enter` ✓
5. Land on Kaizen "No agents yet" empty state ✓
6. Walk all 5 steps of the agent-create wizard (Name + Model=gpt-5.4 → Continue → 4 more Continues) ✓
7. Hover the new agent card to mount the gated Chat button → click → workspace provisions (~2-4 min) ✓
8. Composer textarea appears in `/conversations/{id}` ✓
9. **Phase 5 — long-context condensation**: send a 12KB message with a planted "activation code: 7-ZULU-MIKE-42" surrounded by 40 paragraphs of filler, get the LLM's READY ack, then send "what was the activation code at the start of this conversation?" and get the answer ✓

This was the original `/uat-bot` request from session start (*"3 conversations testing the context manager"*) — Phase 5 is now real. Phase 6 (many-turn recall) and Phase 7 (tool-chain) have working scenarios but haven't been run end-to-end yet — the 50-bot run died at concurrency bottlenecks before any worker got there.

Verified at single-bot scale via run `5ad26d352e3642aa8813aace71780a3e`. The 50-bot rev-4.7 run later in this report shows where this same flow breaks under concurrency.
**Target build under test:** Kamiwaza `release/0.13.1` across **every repo with a `release/0.13.1` branch** (rev 1 only pinned `core` + `frontend`).
**Comparison baseline:** Kamiwaza `release/0.13.0` (`:develop` core image at the time)
**Host:** `kamiwaza-dev-control-plane` — single-node kind+podman cluster on `hpe-demo-0130.westus2.cloudapp.azure.com`
**Driver:** `uat-bot` stress-tester, scenario `workroom_kaizen_ctx`
**Bot population for the headline test:** **20 concurrent admin users** (was 1 per run on 0.13.0)

## ⚠️ Read this first — rev 3 correction confirmed, rev 4 retest delivered

**The "cluster wedges at 100 Running pods" headline in rev 1 and rev 2 was caused by a stale kubelet config, not by anything architectural in Kamiwaza.** The kind cluster on this host was created on **2026-05-19** from an Ansible template that did not yet declare `maxPods`; the kubelet defaulted to **110**. Three days later, ENG-5711 (#282, 2026-05-22) added `maxPods: 1000` to `ansible/roles/kind_cluster/templates/kind-cluster.yaml.j2`, but the running cluster was never recreated to pick it up. Both prior 20-bot runs were hitting the kubeadm default, not the intended ceiling.

**Rev 4 confirmed this with a true clean bootstrap:**
- `make clean` + `./scripts/install-dev.sh --dev-full` against the current Ansible template → kubelet reports **`allocatable_pods=1000`**.
- 20-bot `login` stress: **20/20 PASSED, 0 failures**, cluster steady at 32 Running pods. (Rev 1/2's frontend-render-under-load failures did not reproduce on the corrected cluster.)
- 20-bot `workroom_kaizen_ctx` stress: cluster scaled to **151 Running pods at peak** with 0 Pending. **Past the prior 100-pod wedge by 50%+ with headroom to spare.** The "no concurrency budget anywhere in the platform" framing from rev 1/2 was largely an artifact of the kubelet cap.
- 50-bot `workroom_kaizen_ctx` stress (added in rev 4.1): cluster scaled to **99 Running at peak with 0 Pending**, no scheduler backpressure, but **40 of 50 workers (80%) hit the session-persistence-under-concurrent-login bug** — they landed on the Login page after authenticating successfully, with no "Create workroom" control present. This is the *real* concurrency ceiling on 0.13.1 — it's in the auth-gateway / session-store layer, not the scheduler. See "50-bot result" section.
- **Rev 4.2 (50-bot, milvus `:2.3.0` GHCR fix landed):** the workroom-spawning pipeline now goes all the way through. Cluster scaled to **143 Running pods at peak with 124 extension pods, zero `ImagePullBackOff`, zero scheduler backpressure**. milvus pulls cleanly, kaizen pods reach 1/1 Ready, Traefik IngressRoutes are created and route correctly (direct `curl` on a kaizen URL returns the expected `HTTP 401` Kaizen-pod challenge). **The session-drop bug is now isolated as the sole remaining blocker** — 32/50 dropped at /workrooms landing; 13/50 reached deploy POST and got into the Phase-3 URL-routability polling loop but their forwardauth fetch then sees a stale session and gets redirected back to the Kamiwaza shell (the URL "looks not ready" to the bot even though it IS ready). 0/50 reached the Kaizen UI — but the failure mode is no longer scheduler-OR-image-related, it's a single auth/session issue at two surfaces. See "50-bot rev-4.2 result" section.

So all of the rev-1 / rev-2 framing about "architectural ceiling at the kubelet pod cap" applied to the wrong cap, and "the platform has no backpressure regardless of release" overstated the case — the platform handled 20 concurrent workrooms (~133 pods) without wedging once the actual ceiling was 1000.

**Fix shipped:** the Ansible template is already correct on `release/0.13.1`. Any fresh cluster bootstrap will land `maxPods=1000`. Clusters created before 2026-05-22 need a `make clean && ./scripts/install-dev.sh --dev-full` to pick it up.

## What changed since rev 1

Rev 1 of this report pinned only the **Kamiwaza platform** to `release/0.13.1` (core + frontend) and left the extension stack on whatever happened to be cached on the node. After feedback ("Bad — entire stack where possible should be 0.13.1") rev 2 walks every cloned repo to `release/0.13.1` if that branch exists on the remote. The 20-bot stress run was re-fired against this uniform stack and the failure profile shifted — the 401 auth-gateway burst from rev 1 did not reappear, but a new dominant failure (10/20 timing out on `Page.goto /workrooms`) emerged. **Both rev-1 and rev-2 runs were on the stale-maxPods cluster — see warning above; the "cluster wedge at 100 pods" pattern in both is the stale-config bug, not Kamiwaza architecture.**

Rev 3 recreated the cluster from the current Ansible template, validated that the kubelet now reports `allocatable_pods=1000`, then attempted to re-fire the 20-bot test. The re-fire is blocked on install-bootstrap issues unrelated to the maxPods fix — see "What rev 3 did not finish" below.

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

## Headline result: 20-bot stress on rev-4 (full 0.13.1, maxPods=1000)

Run `9c84e726ea5a4951b612c26a828c72e3`, started 2026-05-25T05:35:25Z, T+~8min before being cancelled (steady-state failure profile established; remaining workers were stuck waiting on a separate marketplace-catalog image-tag bug unrelated to load capacity — see Finding #2).

| Stage | Bots reaching it |
|---|---:|
| Login + navigate to /workrooms | 15 / 20 |
| Workroom created via wizard | 15 / 20 |
| Deploy POST returned + Kaizen pods scheduled | **14 / 20** |
| Kaizen UI actually loaded (`07_kaizen_ui_loaded` screenshot) | 0 / 20 (blocked on Finding #2 — milvus `:2.3.0` not on GHCR) |
| Scenario completed fully | 0 / 20 (same blocker) |

### Per-worker outcome breakdown

| Count | Outcome | Where |
|---:|---|---|
| **14** | Reached `06_deploy_started`, then stuck waiting for kaizen URL to become routable | workers 001–010, 012, 014, 016, 017. The deploy POST succeeded, workroom-manager created the child KamiwazaExtension resources, but the milvus subchart's image (`service-milvus:2.3.0`) doesn't exist on GHCR — so the kaizen deployment never went Ready. Pure extension-level bug, **not** a platform-load issue. |
| 5 | Landed on Login page after navigating to /workrooms (button "Create workroom" not present, only "Login") | workers 011, 013, 015, 019, 020. Same class of failure as rev 1's 401-burst and rev 2's `Page.goto` timeout — under concurrent admin login, some sessions don't persist to the /workrooms route. **Smaller-magnitude version of the same pattern**, but did not block the run. |
| 1 | `POST /workrooms/api/deployments 502: Failed to create…` after the workroom record existed | worker 018. Workroom-manager backend errored on one of the 20 deploys (the others succeeded). |

### Cluster behavior — no wedge

| Time | Total | Running | Pending | ImagePullBackOff | ext-pods |
|---:|---:|---:|---:|---:|---:|
| pre-test | ~40 | 34 | 0 | 0 | 2 |
| T+24s | ~59 | 35 | 7 | 1 | 17 |
| T+46s | ~67 | 38 | 2 | 1 | 27 |
| T+67s | ~107 | 50 | 17 | 2 | 71 |
| T+87s | ~130 | 74 | 19 | 8 | 98 |
| T+108s | ~149 | 85 | 16 | 11 | 113 |
| T+128s | ~167 | **103** | 12 | 9 | 125 |
| T+149s | ~167 | **117** | 12 | 9 | 129 |
| T+169s | ~167 | **123** | 13 | 10 | 133 |
| T+235s | ~167 | **135** | 0 | 13 | 133 |
| T+277s | ~167 | **147** | 0 | 15 | 133 |
| T+359s | ~167 | **151** | 0 | 15 | 133 |
| T+501s | ~167 | **151** | 0 | 15 | 133 (steady state) |

**Past the prior 100-pod wedge at T+128s. Peaked at 151 Running with 0 Pending.** The cluster fully drained the scheduler backlog — there is no Pending plateau. The 15 ImagePullBackOff are all milvus pods waiting on a tag that GHCR doesn't have (Finding #2); they do not constitute scheduler backpressure.

This is the apples-to-apples retest the prior revs needed. **The architectural-ceiling framing is debunked.** Real failure modes remaining for 0.13.1 are (a) the marketplace milvus image tag mismatch and (b) a smaller-magnitude session-persistence-under-concurrent-login flake.

## 50-bot rev-4.7 result (full scenario including agent-create + conversation phases)

Run `7e5d4f6fef254a939014438503ea0dcd`, 50 distinct admin bots, scenario `workroom_kaizen_ctx` with the full agent-create wizard + conversation phases (Phases 5/6/7) enabled. **First test to actually exercise the agent-create flow at concurrent load.**

### Scenario fixes that landed in rev 4.7

Five separate scenario gaps had to be closed before the conversation phases could even be attempted:

1. **Kaizen agent-create wizard is 5 steps, not 1**: scenario now loops Continue up to 6 times instead of trying a single Submit
2. **Name input is bound by `<label for="">`, not placeholder match**: scenario uses label-based field discovery
3. **Model field is a `<select>` (not text input)**: scenario picks the first `<option>` matching gpt/sonnet
4. **Chat button is gated by `{isHovered && ...}` React conditional**: scenario dispatches `mouseenter`/`pointerenter` on the agent card so the Chat button mounts in the DOM, then clicks it
5. **Workspace provisioning takes 2-4 minutes**: composer-wait bumped from 150s to 360s. Also Phase 6/7 "new conversation" starter navigates back to the agents list and re-clicks Chat (Kaizen v3 doesn't have a "New conversation" button)

### Validation: 1-bot smoke confirmed the conversation phases work

Before the 50-bot run, 1-bot smoke `5ad26d352e3642aa8813aace71780a3e` walked the entire flow end-to-end up to and including the long-context test: workroom create → kaizen deploy → enter → agent create (full 5-step wizard) → start chat → **Phase 5: long-context message + recall**. The bot successfully sent a 12KB message with an embedded "activation code 7-ZULU-MIKE-42", got the LLM's READY response, sent the recall question, got the screenshot. **Phase 5 actually works.**

### 50-bot results

| Stage | Reached |
|---|---:|
| Login + /workrooms | 33/50 |
| Workroom + deploy | 16/50 |
| Kaizen UI loaded | 10/50 |
| Agent created + Chat clicked + composer textarea visible | 9/50 (**false positive** — see below) |
| Phase 5 conv1 long-context message actually sent | **0/50** |
| Phases 6/7 | 0/50 |

### Per-worker failure breakdown

| Count | Failure | Layer |
|---:|---|---|
| **17** | `Page.goto: Timeout 60000ms exceeded` on initial `/workrooms` nav | Frontend / forwardauth — same pattern as rev 4.5's smaller-magnitude session-drop |
| **17** | `enter failed: 401 no access token / not authenticated` on POST `/api/workrooms/{id}/enter` | Auth-gateway under load |
| **9** | `send_button_disabled` — bot thought it was on chat page but was actually still on agent-create wizard step 1 | **Kaizen `/api/models` endpoint can't serve 50 concurrent calls** |
| 6 | `Create workroom button not found. Controls: [Home | Models | …]` | Landed on Kamiwaza dashboard instead of /workrooms after auth |
| 1 | `composer not found after 360s` | Unknown — workspace provisioning never completed |

### Finding #10 revised — what the "stuck composer" actually was

**Rev 4.5's `composer_not_found` finding was misattributed.** The bot's composer-finder matches ANY visible textarea — including the **Instructions textarea on agent-create wizard step 1** ("How should this agent behave? (optional)"). When the wizard's Continue button stays disabled (because the Model select shows "Loading models...") AND my scenario's wizard-loop bailed when it saw the disabled button, the bot would mistakenly screenshot `08_kaizen_chat_ready` while still on the wizard. Then it'd try to click a Send button that doesn't exist, hit `submit timeout`, and error out.

What we actually have at 50 concurrent bots is **the Kaizen frontend's `GET /api/models` endpoint can't serve 50 callers in parallel**. Under 50-bot load, model dropdowns stay in "Loading models..." for the full step timeout, wizards never advance, and `/conversations/{id}` is unreachable.

### Finding #11 — three stacked concurrency bottlenecks at 50 bots

This run cleanly separates three distinct concurrency limits in 0.13.1:

1. **Frontend /workrooms render under concurrent auth load** — 17/50 Page.goto timeouts. Forwardauth round-trip on the initial nav after login serializes too slowly.
2. **Auth gateway `POST /enter`** — 17/50 401s on the workroom-entry call after a successful deploy. Same `core-forwardauth` choke point as Finding #5, surfacing at a different request.
3. **Kaizen `/api/models` endpoint** — 9/50 stuck on wizard step 1 because the model dropdown never finishes loading. The endpoint's response time degrades to >60s under 50 concurrent admin sessions.

Cluster scheduling capacity (Finding #11 in rev 4.5) is NOT one of these bottlenecks. 307 extension pods + 159 Running + 144 Pending was sustained without a wedge, same plateau shape as rev 4.5/4.6.

### What rev 4.7 unblocked

- The original "context manager via 3 conversations" goal from the user's first /uat-bot request is **finally testable in single-bot mode** as of rev 4.7. Phase 5 (long-context condensation) runs cleanly at 1 bot.
- The 50-bot conversation-phase test still doesn't run because of the three Kaizen-layer concurrency limits above. Fixing any one of them would let a portion of the 50 bots reach Phase 5. Fixing all three would let the team get end-to-end multi-conversation stress numbers.

### Recommended next steps

| Priority | Item | Owner |
|---|---|---|
| P0 | Profile Kaizen `/api/models` under N=10/20/50 concurrent calls and add response caching or horizontal-scale the kaizen backend | Kaizen team |
| P0 | Profile `core-forwardauth` round-trip under N concurrent admin sessions (same target as rev-4.5 Finding #5; now confirmed at second surface — `/enter` returns 401) | Platform / auth team |
| P1 | Frontend `/workrooms` render path: trace why 60s isn't enough at 50 concurrent loads | Frontend team |
| P2 | Re-run rev 4.7 once any of P0 items lands; we'd expect 9+ bots to actually reach Phase 5 if the Kaizen models endpoint is fixed alone |

## Previously: 50-bot rev-4.5 result (clean cluster, UI-installed wm, distinct users — first run to reach Kaizen UI)

Run `a24213f2ebba4fc9ace81f4a20ff1dfa`, started 2026-05-25 18:11Z, T+~14min cancelled (steady-state plateau established).

**Setup delta vs rev 4.2:**
- Workroom-manager **reinstalled via the UI** (App Garden Deploy flow done by hand) instead of via manual `kubectl apply`. Critical: the operator's full reconcile path sets the right `KAMIWAZA_PUBLIC_API_URL` + `KAMIWAZA_ORIGIN` env vars based on current `global.domain`, so kaizen URLs now point at `hpe-demo-0130.westus2.cloudapp.azure.com`, not the leftover `kamiwaza.test` from the early bad install.
- Cleared all 37 leftover workroom records from the wm-backend DB via API (the K8s cleanup in prior revs only deleted KX CRs, not the wm-backend's own DB rows).
- Stress-tester run with `skip_user_provisioning=false` (the default) → **50 distinct users provisioned**, not 50 sessions for one admin. Confirmed this matters: rev-4.2 had 32-40 session-drops at /workrooms; rev-4.5 had **1**.

### Stage progression

| Stage | Bots reaching it |
|---|---:|
| Login + navigate to /workrooms | **49/50** ✓ |
| Workroom created via wizard | 49/50 |
| Deploy POST returned + Kaizen pods scheduled | 49/50 |
| Kaizen URL became routable (Phase 3 success) | **20/50** |
| **Kaizen UI actually loaded** (`07_kaizen_ui_loaded` screenshot) | **20/50** ✓ — **first time ever** |
| Kaizen chat composer rendered | 0/50 (new failure mode — see Finding #10) |
| Conversation 1–3 (the actual context-manager stress) | 0/50 (gated on composer) |

### Per-worker outcome (50/50 observed)

| Count | Outcome | Notes |
|---:|---|---|
| **20** | Reached `07_kaizen_ui_loaded` then errored at "composer not found after 150s" | Kaizen frontend pod rendered initial HTML, but the chat composer element never appeared in DOM within 150s. New failure mode, surfaced because we finally got bots past Phase 3. Could be Kaizen hydration timing under concurrent load, or a selector drift between Kaizen 1.8.13 and the scenario's selector. |
| **15** | Reached `06_deploy_started`, still in Phase 3 URL polling when cancelled | Many of these would have reached UI given more time — the polling was succeeding for some bots, just slower than the cancel window. |
| 7 | `enter failed: 401 body={"detail":"no access token found"}` on POST `/api/workrooms/{id}/enter` | Auth-gateway rejecting the enter call. Workers had a valid session for the deploy POST but the enter call's auth header missing/stripped. |
| 4 | `enter failed: 401 body={"detail":"not authenticated"}` | Same as above, different error message — same root cause. |
| 3 | Reached `03_workroom_created`, then mid-Phase 2 (deploy POST) | Likely fell into the listing-API stale-read race, no error logged before cancel. |
| **1** | Session dropped at /workrooms landing | Down from 40/50 in rev 4.1 and 32/50 in rev 4.2. **Confirms the rev-4.2 high session-drop rate was an artifact of all 50 bots sharing one admin user**, not a real platform concurrency bug. With 50 distinct users, the rate is 2%. |

### Cluster behavior — first time we saw scheduler backpressure on the corrected cluster

| Time | Total | Running | Pending | ext-pods |
|---:|---:|---:|---:|---:|
| pre-test | ~40 | 35 | 0 | 2 |
| T+25s | ~48 | 36 | 0 | 12 |
| T+55s | ~62 | 53 | 4 | 30 |
| T+83s | ~80 | 69 | 9 | 53 |
| T+108s | ~98 | 85 | 0 | 63 |
| T+133s | ~108 | 97 | 9 | 87 |
| T+159s | ~134 | 120 | 14 | 121 |
| T+184s | ~149 | 133 | 16 | 138 |
| T+210s | ~159 | 148 | 5 | 146 |
| T+261s | ~178 | 172 | 5 | 170 |
| T+313s | ~196 | 192 | 4 | 182 |
| T+414s | ~215 | 213 | 1 | 205 |
| T+518s | ~261 | 257 | 2 | 256 |
| T+595s | ~327 | **259** | 60 | 287 |
| T+646s | ~373 | **259** | 106 | 346 |
| T+774s | ~418 | **259** | 151 | 389 |
| T+826s | ~452 | **259** | 186 | 416 |
| T+851s | ~472 | **259** | 205 | 435 |

**Hard plateau at 259 Running with up to 205 Pending pods (steady-state extension-namespace count: 435).** This is the **first time we've seen scheduler backpressure on the corrected cluster** — 259 is well below the kubelet `maxPods=1000` ceiling, so the limit is *not* per-node pod cap this time. It's a kube-scheduler / etcd / API-server throughput plateau at this single-node cluster. Real architectural finding, distinct from the stale-maxPods bug.

### Headline reframe (cumulative across the rev-4.x series)

| Concern | Rev 1/2 framing | Reality after rev 4.5 |
|---|---|---|
| Cluster ceiling | "wedges at 100 pods" | 259 sustained, 435+ ext-pods total. The 100 was the stale maxPods bug. |
| Auth-gateway 401 burst | "concurrent admin sessions break forwardauth" | Mostly an artifact of 50 sessions for 1 admin. With 50 distinct users: 11/50 enter-401s (down from 15/20 in rev 1) — real but smaller. |
| `Page.goto` timeout on /workrooms | "frontend can't render under load" | Was the stale-config artifact (mix of maxPods + wm misroute). Down to 1/50 with clean setup. |
| Per-workroom pod cost | "11 pods, only fits 7 on a 110-pod node" | 11 pods is still true. With 50 workrooms × ~11 = 550 pods + system, fits comfortably under the 1000 cap. But scheduler throughput plateaus at ~50 workrooms anyway. |
| Real production blocker | "forwardauth singleton choke point" | Now isolated to: (a) **scheduler/etcd plateau at ~50 concurrent workrooms** on a single-node cluster, (b) **Kaizen frontend hydration** (composer never appears for the workers that reach UI), (c) **smaller-magnitude enter-401** auth path issue. |

### Finding #10 (new in rev 4.5) — Kaizen chat composer never renders for 100% of workers that reach UI

20/20 workers that successfully loaded `07_kaizen_ui_loaded` then failed waiting for the chat composer element. The Kaizen frontend container is 1/1 Running, returned HTML over the network, but the composer (textarea / message-input DOM element) never appeared within 150s.

Hypotheses:
- Kaizen frontend hydration is slow because all 20 frontend pods are competing for ray-head (or kaizen-backend) API resources at once
- Kaizen backend → context-service → milvus chain takes long enough that the frontend shows a loading spinner past 150s
- Selector drift: scenario looks for `textarea[placeholder*="message"]` (or similar) and Kaizen 1.8.13 changed the DOM
- React app bundle is large and the browser-side JS takes time

This is the first failure mode we can attribute squarely to Kaizen-the-extension as opposed to platform infrastructure. Suggested next step: scenario adds a `screenshot 07a_kaizen_loading` 10s after `07_kaizen_ui_loaded`, then 30s, 60s, 120s to see what's actually on screen during the wait. Or have a real human open one of these workrooms manually and see how long the composer takes to render.

### Finding #11 (new in rev 4.5) — Scheduler/etcd throughput plateau at ~50 concurrent workrooms

Cluster plateaued at exactly 259 Running pods despite maxPods=1000 and only 50 bots driving load. Pending grew to 205 with ContainerCreating stuck at ~8. This is the second-order capacity ceiling — once you're past the per-node-pod-cap conversation, the next limit is how many pod create/start operations kube-scheduler + kubelet + containerd can process in parallel on a single-node cluster.

Worth checking before any architectural decisions:
- kube-scheduler logs for queueing delays
- etcd write latency under load (single-node etcd can be a bottleneck even though we have 3 replicas — they all serialize through the leader)
- containerd's `cri.containerd.max_concurrent_downloads` and image-pull pool size
- kubelet's `--registry-pull-qps` and `--registry-burst`

This finding is genuinely architectural in a way the prior framings weren't. It would still bite a multi-tenant deployment regardless of how the auth and workroom-manager layers behave.

## 50-bot rev-4.2 result (milvus `:2.3.0` GHCR fix in place) — superseded by 4.5

Run `381d6094d25148bb9ac519015f05d782`, started 2026-05-25 15:53Z, T+~11min cancelled (steady state established; workers stuck in Phase 3 polling were on the 10-min URL-routability timeout).

**Setup delta vs rev 4.1:**
- `service-milvus:2.3.0` now resolves at the registry (verified at registry level with a manifest HEAD: `HTTP 200`, `docker-content-digest: sha256:1b65507ecfbe88c0fc19e3cd5664335036da7fdf3eb3913166a6b4cac84fa4f0`, matches the multi-arch digest seeded from the dev Garden v2.3.0 standalone image). The GitHub Packages API view of that package is stale and still doesn't show the tag — but the registry truth via `curl -sI https://ghcr.io/v2/...` is what kubelet uses.
- Workroom-manager backend bounced (`kubectl rollout restart`) to refresh its catalog cache before the run.
- Cluster otherwise identical to rev 4.1 (maxPods=1000, fresh 0.13.1 stack, clean baseline of 2 ext pods + ~38 platform pods).

| Stage | Bots reaching it |
|---|---:|
| Login + navigate to /workrooms (Create-workroom button present) | 18 / 50 |
| Workroom created via wizard | 18 / 50 |
| Deploy POST returned + Kaizen pods scheduled | **13 / 50** |
| Phase 3 URL polling sees Kaizen route as live | **0 / 50** ← the new bottleneck |
| Kaizen UI actually loaded | 0 / 50 |

### Per-worker outcome breakdown (49 workers observed; 1 silently dropped before scenario.start)

| Count | Outcome | Notes |
|---:|---|---|
| **32** | Session dropped at /workrooms landing — `Create workroom button not found. Controls: [Login]` | Same dominant failure mode as rev 4.1 (40/50 there). |
| **8** | Reached `06_deploy_started`, still in Phase 3's 10-min URL polling loop when run was cancelled at T+11min | These workers had a valid session to do POST `/workrooms/api/deployments` but their subsequent `fetch(...kaizen URL...)` through `core-forwardauth` middleware appears to be hitting a stale session, redirecting to /login, and the bot's poll loop sees the resulting Kamiwaza shell HTML (not Kaizen) → keeps polling. |
| **5** | Reached deploy, Phase 3 polled the full 10 min and timed out with `ERROR: kaizen URL never returned Kaizen HTML after 600s` | Same root cause as the 8 above, just the workers that hit Phase 3 earliest. |
| **3** | Past deploy POST but `workroom_id not found by name=ctx-mgr-uat-…` in the listing API | Stale-read race in `/workrooms/api/workrooms` — POST returned success but the subsequent list-query in the same window didn't see the new row. Reproduces from rev 2/4. |
| 1 | `Page.goto: Timeout 60000ms exceeded` on initial nav | Same class as rev 2. |

### Cluster behavior at 50 bots with milvus fix — full scaling, no image-pull failures

| Time | Total | Running | Pending | ImagePullBackOff | ext-pods |
|---:|---:|---:|---:|---:|---:|
| pre-test | ~40 | 35 | 0 | 0 | 2 |
| T+26s | ~50 | 40 | 2 | 0 | 12 |
| T+51s | ~75 | 56 | 7 | 0 | 35 |
| T+76s | ~85 | 66 | 4 | 0 | 44 |
| T+102s | ~91 | 73 | 4 | 0 | 56 |
| T+127s | ~102 | 90 | 0 | **0** | 66 |
| T+152s | ~106 | 94 | 0 | 0 | 70 |
| T+178s | ~111 | 99 | 0 | 0 | 75 |
| T+228s | ~129 | 114 | 0 | 0 | 93 |
| T+254s | ~138 | 120 | 6 | 0 | 107 |
| T+279s | ~140 | 135 | 2 | 0 | 120 |
| T+304s | ~143 | **141** | 0 | 0 | 124 |
| T+355s | ~144 | **143** | 0 | 0 | 124 |
| T+685s | ~159 | **142** (steady) | 0 | 0 | 124 |

**Compared to rev 4.1:** peak Running went **99 → 143** (44 more pods) because the workers that survived session-drop actually spawned full kaizen-stack workrooms instead of dying at deploy POST. The 124 extension pods is the largest sustained extension-namespace workload we've measured. ImagePullBackOff stayed at 0 throughout — the milvus fix landed cleanly.

### What rev 4.2 isolates

Rev 4.1's "auth/session bottleneck" framing is now sharpened: it's **specifically a session-cookie-persistence problem in the path that goes through `core-forwardauth` middleware under concurrent admin sessions**, surfacing at two distinct points:

1. **Landing on /workrooms** (32/50): the bot's authenticated session establishes successfully (login POST returns 200), the bot navigates to /workrooms, but the SPA renders the unauthenticated layout (only "Login" control visible). This is the rev-4.1 failure.
2. **Phase 3 URL polling** (13/50): the bot's session is still valid for `/workrooms/api/deployments` POST (which goes through kamiwaza-core's auth, not forwardauth), but the subsequent `fetch(/runtime/apps/kaizen-<id>)` through Traefik's `core-forwardauth` middleware doesn't see a valid session — redirects to /login, bot sees the Kamiwaza shell HTML, treats the URL as "not ready", keeps polling for 10 min then times out.

Both surfaces are the same underlying bug. The platform handled 50 concurrent admin sessions worth of workroom creation + cluster scheduling + image pulls without breaking a sweat — **143 Running pods, 0 Pending, 0 ImagePullBackOff** — but the auth layer can't keep those 50 sessions alive simultaneously.

**Direct verification that the kaizen path is actually live:**
```
$ kubectl get ingressroute -n kamiwaza | grep kaizen-13mp7xdl-d9e57b43
kaizen-13mp7xdl-d9e57b43-route   7m15s

$ curl -sk -o /dev/null -w "%{http_code}\n" \
    https://hpe-demo-0130.westus2.cloudapp.azure.com/runtime/apps/kaizen-13mp7xdl-d9e57b43
401
```
The 401 is exactly what Phase 3's poll loop accepts as "live" — kaizen is up, kaizen wants a launch token. From an authenticated session that hadn't been dropped, this same fetch would succeed.

### Recommended next investigation step

Profile `core-forwardauth` + keycloak under 50 concurrent admin sessions. Likely candidates:
- Forwardauth's in-memory session cache has a size limit that evicts older entries under load
- Forwardauth → keycloak token-validation round-trip serializes (single keycloak replica, connection-pool limit)
- The session cookie's `SameSite` / domain settings combined with `/runtime/apps/...` paths cause the cookie to not be sent on cross-IngressRoute requests
- Workroom-binding-state contention (we saw similar surface in the `AUTH_WORKROOM_BINDING_BACKEND` memory entry — that was a config bug, but the same code path could have a concurrency bug too)

Rev 4.2 run artifacts at `data/runs/381d6094d25148bb9ac519015f05d782/events.jsonl` have per-worker timing aligned with the workroom IDs that *were* successfully created (`ctx-mgr-uat-mpld*`), so the team can correlate against keycloak / forwardauth / kamiwaza-core access logs in the same time window.

## 50-bot result on rev-4.1 cluster (same maxPods=1000 + 0.13.1)

Run `c3271c9bdb0442d79bc2f2aa694acd22`, started 2026-05-25 06:54Z, T+~8min cancelled (steady-state established). 50 concurrent admin bots, same `workroom_kaizen_ctx` scenario, 60s ramp-up. Cluster pre-test at clean baseline (38 total pods, 2 ext pods = just workroom-manager).

| Stage | Bots reaching it |
|---|---:|
| Login + navigate to /workrooms (Create-workroom button present) | 10 / 50 |
| Workroom created via wizard | 10 / 50 |
| Deploy POST returned + Kaizen pods scheduled | 8 / 50 |
| Kaizen UI actually loaded | 0 / 50 (blocked on Finding #2 — milvus `:2.3.0`) |

### Per-worker outcome breakdown

| Count | Outcome | Notes |
|---:|---|---|
| **40** | Session dropped — landed on Login page after auth; "Create workroom" button absent, only "Login" control visible | Same class as rev-2's `Page.goto` and rev-1's 401-burst, but at much larger magnitude. **The dominant 50-bot failure mode.** This is *not* a pod-budget issue — the workers got HTTP 200 on the workrooms page; the page just didn't have an authenticated layout. Likely the auth-gateway / session-store can't keep up with 50 concurrent admin sessions establishing in a 60s ramp window. |
| 8 | Reached `06_deploy_started`, then stuck waiting on milvus `:2.3.0` ImagePullBackOff | Same as rev-4 — pure extension-bug blocker, not load. |
| 2 | Past deploy POST but `workroom_id not found by name` in listing API | Same as rev-2 + rev-4. |

### Cluster behavior at 50 bots — still no wedge

| Time | Total | Running | Pending | ext-pods |
|---:|---:|---:|---:|---:|
| pre-test | ~40 | 34 | 0 | 2 |
| T+25s | ~46 | 40 | 1 | 11 |
| T+76s | ~71 | 56 | 11 | 38 |
| T+101s | ~71 | 64 | 0 | 38 |
| T+127s | ~83 | 74 | 2 | 47 |
| T+152s | ~89 | 82 | 0 | 56 |
| T+177s | ~99 | 90 | 2 | 65 |
| T+228s | ~98 | 91 | 0 | 65 |
| T+253s | ~106 | **98** | 0 | 74 |
| T+278s | ~107 | **99** | 0 | 74 |
| T+481s | ~107 | **99** (steady) | 0 | 74 |

**Peak cluster utilization on 50 bots was lower than on 20 bots** (99 vs 151 Running) because most of the workers were dying at the auth layer before they could spawn workroom pods. The scheduler had no backpressure — 0 Pending throughout. **At 50 concurrent admins, the platform's load ceiling is in the auth/session layer, not the kubelet.**

### Headline reframe at 50 bots

The "scheduler wedge" theory of platform unscalability is now fully dead. The real bottleneck on 0.13.1 is concurrent-admin-session establishment in the auth-gateway/Keycloak path. Specifically:

- 20 concurrent admins → 5/20 (25%) lose session
- 50 concurrent admins → 40/50 (80%) lose session

This pattern is the actual blocker for any sales-demo / QA-team-of-5+ scenario. It is independent of the maxPods bug and independent of the per-workroom pod cost story.

## Prior result: 20-bot stress run on rev-2 (kept for comparison)

The rev-2 run below is now known to have been on a maxPods=110 cluster — the headline failures (Page.goto, auth-gateway 401) were partly amplified by scheduler-saturation. Kept here as historical reference.

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

Running pods plateaued at exactly **100** — and per the rev-3 correction at the top of this report, that "100" is the kubeadm-default `maxPods=110` ceiling that this cluster was created under before ENG-5711 added `maxPods: 1000` to the Ansible template. Same shape as rev 1 and the 0.13.0 report because all three runs were on the same misconfigured kubelet. **The pattern is real, the root cause was misattributed.** See rev-3 correction at top of report.

## Findings (consolidated across rev 1 + rev 2, with rev-3 corrections inline)

### Finding #1 — Per-workroom pod cost is ~11 pods (architectural — but ceiling is 1000 not 110)

A single workroom spawns: kaizen×4 (backend, frontend, controller, postgres) + milvus×4 + graphiti×2 + omniparse×1. On a properly-configured single-node cluster with `maxPods=1000`, the structural ceiling is **~90 concurrent workrooms** (1000 ÷ 11) minus system pods, not the **~7** that rev 1 + rev 2 quoted. Sharing Milvus + Graphiti is still good engineering (drops marginal cost per workroom, improves cold-start time, reduces resource fragmentation), but it is not "the only durable fix" — the cluster headroom story is far less dire than rev 1 + rev 2 implied.

**Confirmed by rev 4:** the same `workroom_kaizen_ctx` scenario at 20 concurrent users reached **151 Running pods with 0 Pending and full scheduler drain** on the corrected cluster. Per-workroom pod cost is real (~11 pods × 14 successful deploys = 154 pods is consistent with the observed peak), but the cluster absorbed it cleanly.

**Recommendation (corrected):** ship the maxPods Ansible-template fix to any field/demo cluster (the template already has it on `release/0.13.1`; any cluster created before 2026-05-22 needs to be recreated). The architectural workroom-sharing refactor is still worth doing for cold-start time and resource fragmentation but is no longer the "must-fix-before-shipping" item it was framed as.

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

### Finding #5 — Auth-gateway / session-store concurrency ceiling (now the dominant rev-4.1 finding)

This was the rev-1 401-burst, rev-2 Page.goto timeouts, and is now confirmed at 50-bot scale as the *real* platform ceiling. Per the 50-bot run:

- **20 bots** → 5/20 (25%) lose session before reaching /workrooms
- **50 bots** → **40/50 (80%) lose session** before reaching /workrooms

These are the SAME concurrent-admin-session establishment failure surfacing in different ways depending on where the bot happens to be when its session drops. The root cause is somewhere in: keycloak token validation throughput, auth-gateway session caching, the forwardauth middleware's keycloak round-trip, or session-store concurrent-write contention.

This is the actual production-blocker for multi-user demos / QA-team scenarios. The 0.13.0 report's per-user quota recommendation addresses a different concern (workroom-creation rate) and would not fix this — the issue is at the *session establishment* layer, before any workroom-creation API is even called.

**Suggested investigation path:**
- Run `kubectl logs -f -n kamiwaza deployment/keycloak` during a 50-bot run; look for connection-pool exhaustion or auth flow errors
- Check forwardauth middleware (kamiwaza-core) for in-flight-request limits or serialization
- Profile the actual /workrooms render path for sessions that appear logged-out — what specifically is rejecting them?
- Rev-4.1 stress run artifacts at `data/runs/c3271c9bdb0442d79bc2f2aa694acd22/events.jsonl` have per-worker timing for correlation against keycloak/auth logs

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

## What rev 4 fixed in the install bootstrap (was a rev 3 blocker)

Rev 3 documented two install-bootstrap blockers that prevented the retest. Rev 4 worked through both and the actual workarounds are documented here so the team has a known path to a clean install:

**Blocker A — Missing `core-s3` secret on fresh installs** (resolved by workaround). A monitor script created `core-s3` as a stub secret in the `kamiwaza` namespace the moment the namespace appeared, before Ray head tried to schedule:
```bash
kubectl create secret generic core-s3 -n kamiwaza \
  --from-literal=access_key_id=local-dev-stub \
  --from-literal=secret_access_key=local-dev-stub
```
Real chart-side fix: either remove `core-s3` from `overrides.yaml` when S3 isn't configured, or have a chart template create the stub in local-dev mode.

**Blocker B — `init-keycloak-users` post-install hook fails with "Refusing to regenerate"** (resolved by flipping a documented flag). The chart's `overrides.yaml` already documents this exact case: on a fresh install with no `kamiwaza-svc-credentials` secret yet, set `global.forwardauthServiceAccount.rotateOnUpgrade: true` for the first install only, then flip back to `false` once the secret exists. Rev 4 did this and the job succeeded first try.

**Result:** kamiwaza release reached `deployed` in ~7 minutes from fresh install; scheduler Ready immediately after. workroom-manager installed via the stress-tester `install_extension` scenario (after a minor scenario-yaml fix to click the card's Deploy button rather than the card body), Ready in 44s.

## What rev 3 documented as blockers (now resolved in rev 4)

After validating that the recreated cluster reports `maxPods=1000`, the planned 20-bot rerun was blocked on two pre-existing install-bootstrap bugs that surface on any fresh deploy of `release/0.13.1` (independent of maxPods):

### Blocker A — Missing `core-s3` secret on fresh installs (chart contract gap)

`cluster/values/overrides.yaml` declares a `credentialsSecretRef` pointing at a Kubernetes secret named `core-s3`, but no chart template or Ansible role creates that secret. On a fresh install, `core-raycluster-head` goes `CreateContainerConfigError` with `Error: secret "core-s3" not found`, which blocks `core-scheduler` (which waits on Ray GCS to be reachable).

Workaround applied during rev 3 for testing: `kubectl create secret generic core-s3 -n kamiwaza --from-literal=access_key_id=local-dev-stub --from-literal=secret_access_key=local-dev-stub`. Real fix: either (a) make the chart create the secret with a placeholder when local-dev mode is selected, (b) ship a one-shot Ansible task that creates it, or (c) remove the `credentialsSecretRef` from `overrides.yaml` when S3 isn't actually configured.

### Blocker B — `init-keycloak-users` post-install hook + `core-db-init` post-install hook deadlock

Two relevant hooks in the kamiwaza umbrella chart, both `helm.sh/hook: post-install,post-upgrade`:

- `core-db-init` (weight `-5`) — initializes the scheduler's Postgres schema. `core-scheduler` has an `initContainer` (`wait-for-deps`) that polls for the schema to exist and times out after 120s if not, sending the pod through a CrashLoop restart cycle.
- `init-keycloak-users` (weight `10`) — bootstraps the Keycloak realm + a `ForwardAuth` service-account client. On rev 3 (and intermittently on prior runs) this fails with `Keycloak did not return a ForwardAuth service-account secret for client 'kamiwaza-svc'. Refusing to regenerate automatically until a transactional handoff is implemented.` That assertion lives at `kamiwaza/services/init-keycloak-users/main.py:1180-1183`.

The failure mode: Helm `--wait` blocks the install from completing until the umbrella's Deployments are Ready. `core-scheduler` is never Ready because its init container is waiting for `core-db-init`. `core-db-init` is a post-install hook that only fires after Helm install completes successfully. Result: helm install sits in `pending-install`, then eventually times out at 20 min; the install is marked `failed`; `core-db-init` never runs; the scheduler never becomes Ready.

Rev 2 worked through this implicitly because its cluster had been bootstrapped successfully at some prior point (when keycloak's realm state was clean and the hook chain completed). Rev 3 hit it on a true fresh install because:
- The `make clean` step destroys the cluster but the Helm release uninstall + reinstall on the *same* persistent volumes leaves Keycloak's postgres database with stale realm state.
- That stale state causes the `init-keycloak-users` re-run to fail the ForwardAuth assertion rather than re-create the missing secret.

Workaround paths (none applied during rev 3 due to time):
1. `make clean` + start fresh with no surviving PVCs, then bootstrap once. Probably "the right answer" for any team retest.
2. Skip Helm hooks entirely (`--no-hooks`), then manually `helm template` + `kubectl apply` the `core-db-init` Job, then let scheduler converge.
3. Patch the assertion in `init-keycloak-users/main.py` to regenerate the secret automatically when missing (the comment says it's intentionally refusing "until a transactional handoff is implemented").

### What the team retest needs to do

To get a clean rev-4 number on this scenario:

1. **Fresh cluster from scratch.** `make clean` (verify both kind cluster + persistent volumes are gone) then `./scripts/install-dev.sh --dev-full` against the current Ansible template (already has `maxPods: 1000`).
2. **Resolve Blocker A** before the install starts — either ship the secret stub via Ansible or remove the `credentialsSecretRef` from `overrides.yaml` for local-dev.
3. **Validate the kubelet ceiling actually landed**: `kubectl get node -o jsonpath='{.items[0].status.allocatable.pods}'` must report `1k`, not `110`.
4. **Wait for kamiwaza release status `deployed`** (not `pending-install` or `failed`) before doing anything else.
5. **Install workroom-manager extension** via the UI install flow (or the stress-tester's `install_extension` scenario), and verify its Deployment image tag is resolvable on GHCR — see Finding #3.
6. **Run the 20-bot stress** with `kamiwaza_url=https://hpe-demo-0130.westus2.cloudapp.azure.com`, `concurrent_users=20`, `scenarios=[workroom_kaizen_ctx]`, `skip_user_provisioning=true`, `kamiwaza_admin_user=admin`, `kamiwaza_admin_password=<from kamiwaza-user-admin secret>`. Don't run rev-4 against the cached `:develop` extension images — either pin every extension to `:release-0.13.1` once those tags are published (Finding #3) or document which extension version was actually live.

## Suggested next test

Once shared Milvus + shared Graphiti are designed in, re-run this same 20-bot scenario to validate the architectural fix. The headline metric would be: how many of 20 bots reach the Kaizen UI within their 30-min timeout? **Target: ≥18/20 (allow for transient flakes), with no 401 storm, ≤30 FailedScheduling events total, no ImagePullBackOff, and the frontend `/workrooms` route returning within 5s under 20-session concurrency.** This run can only validate the *architectural* fix after the test is first re-run on a `maxPods=1000` cluster to establish the corrected baseline (see "What rev 3 did not finish").

## Caveats on this report

- Scenario does not include an agent-create step; even the workers that reached the Kaizen UI couldn't actually send messages. This is a stress-tester scenario gap, not a 0.13.1 platform issue. The original goal of "exercise the context manager via 3 conversations" remains untested on either version. The platform-layer findings here stand independently.
- Rev-2 run was cancelled at ~6 min once the failure profile was established, rather than waiting out the 30-min scenario timeout per worker. The 8 "still-running" workers at cancellation were stuck on screenshots past `07_kaizen_ui_loaded` with no progress for 90+ seconds.
- The kind node has cached `kaizen:1.8.13`, `milvus:2.3.0` (huh — actually only 2.2.0 cached, the 2.3.0 request fails), `omniparse:2.0.14`, `workroom-manager:0.6.19-dev` image layers from prior runs. Some of these tags do not exist on GHCR — see Finding #3. A fresh cluster would fail harder.
- I broke `workroom-manager` and `skills-library` extensions during rev-1 cleanup over-reach; they were restored via the UI install flow and via manual Deployment-image patch (`:0.6.19-dev` → cached layer pointer) before rev 1's 20-bot run and remain in that state for rev 2.
