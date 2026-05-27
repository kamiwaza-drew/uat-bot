# Systematic debugging — root cause for 88% failure at 100-concurrency (a826c0f4 - 12/100 success)

## Reproduction

Run `a826c0f4` (2026-05-27 06:11–07:23 UTC), 100 bots, 4-bot/min ramp, 15-turn scenario.
Outcome: 12 success, 78 error, 10 unaccounted.

## Three failure regimes, not one

Sorted by bot start offset:

| Workers | Start window | Outcome | Failing step | What was actually missing |
|---|---|---|---|---|
| 001–012 | 0–173 s | succeed (1244–1438 s) | — | — |
| 013–050 | 182–794 s | "composer not found after 1200 s" | step 32 (post-Chat-click) | kaizen pod Ready, but `handleStartChat` workspace pod never lands |
| 051–100 | 808 s+ | "kaizen URL never returned HTML" | step 14 (kaizen-readiness) | kaizen's own 4 pods never reach Ready in 15 min |

Plus scattered "Create workroom button not found" and "workroom_id not found" — same pile-up surfacing in workroom-manager UI, not separate bugs.

## What I verified

- **Operator concurrency = 1.** [operators/internal/controller/extensions/kamiwazaextension_controller.go:2119-2133](operators/internal/controller/extensions/kamiwazaextension_controller.go#L2119-L2133) — `SetupWithManager` calls `.Complete(r)` with no `controller.Options{MaxConcurrentReconciles: N}`; controller-runtime defaults to 1.
- **But each reconcile is fast object CRUD** (RBAC + Secret + ConfigMap + Deployment + Service + IngressRoute) — does not block on pod-Ready. So the operator's serial loop is not the dominant cost.
- **Per-kaizen sandbox-controller DOES block.** [kamiwaza-extensions-kaizen/apps/kaizenv3/packages/kaizen-workspace/kaizen/sandbox_controller/backends/kubernetes.py:164-198](kamiwaza-extensions-kaizen/apps/kaizenv3/packages/kaizen-workspace/kaizen/sandbox_controller/backends/kubernetes.py#L164-L198) — `create()` → `_create_resources()` → `_wait_for_ready_or_cleanup()` awaits pod-Ready synchronously. When kubelet is jammed, every `handleStartChat` waits behind the queue.
- **Single-node kind cluster.** Only `kamiwaza-dev-control-plane`. 1 kubelet, 1 podman/containerd, 1 image cache. Pod cap (1k) was not hit.
- **CPU is not the bottleneck.** Peak was 72 % requests / 27 % actual. The saturation is in the pod-creation pipeline (PLEG + containerd pull/unpack + volume init), not compute.
- **Traefik logs clean** — IngressRoute reconciliation is not lagging.
- **workroom-manager** fires deploy POSTs at consistent ~15 s intervals — not a serialization point.

## Hypothesis

The dominant choke is the **single-node kubelet/containerd container-creation pipeline**, with two amplifiers: the operator's `MaxConcurrentReconciles=1` and each kaizen's sandbox-controller serializing workspace-pod creation.

100 bots × 4 kaizen pods + 100 agent workspace pods = ~500 pod creations queued on one kubelet. First ~12 bots clear before the queue fills (regime A). Bots 13–50 get their 4 kaizen pods up, but by the time their sandbox-controller asks for the workspace pod, the pull/unpack queue is hopelessly behind — composer never renders (regime B). Bots 51+ can't even get the 4 kaizen pods scheduled fast enough (regime C).

Consistent with earlier-run evidence (workers 75/95 succeeding at 700–830 s — not a hard cap, a long queue draining).

## Recommended fix, ordered by leverage

1. **Multi-node kind cluster** (real fix). The bottleneck is one kubelet — add 2-3 worker nodes; pods spread across kubelets, image pulls parallelize per node. Only change that lifts the actual ceiling.
2. **Bump operator concurrency.** One-line at [operators/internal/controller/extensions/kamiwazaextension_controller.go:2120](operators/internal/controller/extensions/kamiwazaextension_controller.go#L2120) — `.WithOptions(controller.Options{MaxConcurrentReconciles: 10}).` Cheap, safe, eliminates the operator as a contributor once node pool grows.
3. **Admission control in workroom-manager.** Return 429 from `POST /api/deployments` when in-flight kaizen count > ~20. Pushes back-pressure to the client instead of letting bots queue 50-deep with no hope.

For the harness: drop ramp to ~2/min until #1 lands. Current cluster sustained-deploy rate is ~4/min; 4/min ramp leaves zero margin.

Recommend landing #2 immediately (one line, no risk), then #1 once node count agreed. #3 is the right enterprise behavior but a larger change.
