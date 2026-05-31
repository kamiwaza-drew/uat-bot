# Kaizen GPT-5-Nano Workroom Distinct-User Rerun Results

Date: 2026-05-30
Target: `https://ec2-3-147-134-21.us-east-2.compute.amazonaws.com`
Scenario: `workroom_kaizen_steady_15turn_gpt5nano`
Flow shape: distinct provisioned users, distinct fresh workrooms, fresh Kaizen deploy per workroom

## Executive Summary

The earlier workroom browser timeouts were partly inflated by a UAT-bot detector bug. Kaizen's conversation events API returns `{ "events": [...] }`, and the scenario was incorrectly looking for a raw array or `items`. After fixing that and disabling browser-side caching for `/api/conversations/{id}/events`, the 1-user smoke run cleanly detected chat replies.

That detector fix did not change the 15-user product outcome enough to claim success.

With the corrected detector:

- `1` user smoke: pass
  - Turn 1: `4195ms`
  - Turn 2: `2360ms`
  - Turn 3: `4080ms`
- `15` users: setup improved, chat still unstable
  - `15/15` users created workrooms
  - `15/15` Kaizen deployments started
  - `15/15` reached deploy-ready
  - `15/15` bound workroom session
  - `15/15` reached chat-ready
  - Turn 1: `5 success`, `10 timeout`
  - Turn 2: `3 success`, `8 timeout`, `4 composer not found`
  - Turn 3: `1 success`, `8 timeout`, `6 composer not found`

Bottom line: Kaizen startup/deploy throughput is much better, but chat/runtime stability under `15` fresh concurrent workroom users is still not good enough.

## What Changed In The Harness

The scenario helper now:

- reads `body.events` from `/api/conversations/{id}/events`
- disables browser caching with `cache: "no-store"` plus cache-busting query params
- polls new events using `offset=<before_event_count>` instead of slicing a repeatedly cached full list

This change fixed false negatives in the browser harness. Before the patch, Kaizen was visibly replying in the UI and persisting `FinishAction` rows in Postgres, but the scenario still reported `TIMEOUT`.

## 1-User Smoke

Run: `cd256fb138354737a3ca8549951c0a2c`

Observed turn timings before cancellation:

- Turn 1: `4195ms`
- Turn 2: `2360ms`
- Turn 3: `4080ms`

This was the gate used to prove the detector fix before promoting to the `15`-user run.

## 15-User Run

Run: `4a4a884bd6a041cba4c14ac7b5a307ac`

### Setup/creation path

- `15/15` reached step `15` (`deploy started`)
- `15/15` reached step `17` (`deployment ready`)
- `15/15` reached step `18` (`session bound`)
- `15/15` reached step `32` (`chat button -> conversation`)
- `15/15` reached step `35` (`composer ready`)

This is a real improvement over the earlier release behavior, where the system often fell over before steady chat load even began.

### Turn results

Turn 1:

- Successes: `5`
- Timeouts: `10`
- Composer missing: `0`

Turn 2:

- Successes: `3`
- Timeouts: `8`
- Composer missing: `4`

Turn 3:

- Successes: `1`
- Timeouts: `8`
- Composer missing: `6`

Representative successful lines:

- worker-008 turn 1: `response_ms=10136`
- worker-003 turn 1: `response_ms=11537`
- worker-001 turn 1: `response_ms=14740`
- worker-011 turn 1: `response_ms=14580`
- worker-015 turn 1: `response_ms=18193`

Representative failures:

- many workers timed out even after reaching chat-ready
- several sessions degraded into `ERROR turn N: composer not found` by turn 2 or turn 3

## Interpretation

The corrected detector means these results are much more trustworthy than the earlier browser-run numbers.

The remaining problem is not "could the test see the replies?" anymore. The remaining problem is the product: after `15/15` users reach chat-ready, many sessions still degrade under concurrent turn load, and several workers lose the composer entirely after one or two turns.

The recurring browser-side `401` noise against runtime context endpoints is still present during these runs, and it remains strongly correlated with later chat degradation.

## Artifacts

- Smoke metrics: `uat-bot/data/runs/cd256fb138354737a3ca8549951c0a2c/metrics.jsonl`
- 15-user metrics: `uat-bot/data/runs/4a4a884bd6a041cba4c14ac7b5a307ac/metrics.jsonl`
- 15-user events: `uat-bot/data/runs/4a4a884bd6a041cba4c14ac7b5a307ac/events.jsonl`

