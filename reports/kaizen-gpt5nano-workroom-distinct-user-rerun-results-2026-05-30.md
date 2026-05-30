# Kaizen GPT-5-Nano Workroom Distinct-User Rerun Results

Date: 2026-05-30  
Target: `https://ec2-3-147-134-21.us-east-2.compute.amazonaws.com`  
Scenario: `workroom_kaizen_steady_15turn_gpt5nano`

## Executive Summary

The latest Kaizen auth/runtime fix from PR `kamiwaza-extensions-kaizen#340` materially improved the fresh-workroom flow, and a small `uat-bot` scenario fix unblocked the runtime-app browser handoff by normalizing Kaizen runtime URLs to include a trailing slash.

After those changes:

- A `1`-user smoke run successfully created a fresh workroom, deployed Kaizen, created the first agent, and received a GPT-5-nano response.
- A `15`-user distinct-user run successfully created `15/15` workrooms, started `15/15` Kaizen deploys, reached `DEPLOYED` for `15/15`, entered `15/15` workrooms, and opened the Kaizen agent wizard for `15/15`.
- The remaining blocker is conversation durability under concurrent chat load. In the `15`-user run, first-turn success was only `6/15`, second-turn success was `5/15`, and the rest timed out or degraded into `composer not found` by turn 3.

This means the workroom create/deploy/auth path is significantly healthier than before, but Kaizen still does not pass a realistic `15`-concurrent-user chat test.

## Changes Applied Before Rerun

Kaizen PR `#340`:

- Preserved platform auth/cookie behavior for Core/workroom-bound platform calls instead of forwarding runtime bearer auth into those routes.
- Kept the previously added startup/concurrency fixes and release-branch scaling knobs.

Local test harness adjustment in `uat-bot`:

- Normalized `/runtime/apps/<deployment>` URLs to `/runtime/apps/<deployment>/` before browser navigation.
- Without the trailing slash, the browser handoff landed on a blank white page and the scenario stalled before Kaizen UI interaction.

## Runs

| Run | Shape | Auth mode | Result |
| --- | --- | --- | --- |
| Smoke | 1 user, fresh workroom | direct `admin` login | Pass to live chat: turn 1 `response_ms=4070`, turn 2 `response_ms=5186` before manual stop |
| Distinct-user load | 15 users, 15 fresh workrooms | provisioned `editor` users | Setup pass, chat fails under load |

Run IDs:

- Smoke: `6f0a4050ccf743f3a054eb275d7ac86c`
- Distinct-user load: `ac4a2d83fbcc4fa08277b3c55a1bbd60`

## Key Findings

### Fixed Enough To Reach Live Kaizen For All 15 Users

In the `15`-user distinct-user run:

- `15/15` reached `/workrooms`
- `15/15` started Kaizen deploys
- `15/15` reached deployment-ready
- `15/15` successfully entered their workrooms
- `15/15` reached the Kaizen agent-create flow
- `15/15` selected `gpt-5-nano`

This is a major improvement over the earlier workroom-shaped runs that failed before or during fresh deployment/auth handoff.

### Remaining P1: Chat Stability Fails Under 15 Distinct Concurrent Users

Observed turn outcomes from the `15`-user run:

- Turn 1: `6 ok`, `9 timeout`
- Turn 2: `5 ok`, `10 timeout`
- Repeated downstream UI degradation: `composer not found` errors beginning at turn 3

Examples:

- `worker-001`: turn 1 `24312ms`, turn 2 `TIMEOUT`, then `composer not found`
- `worker-004`: turn 1 `15854ms`, turn 2 `10350ms`
- `worker-005`: turn 1 `TIMEOUT`, turn 2 `17291ms`, turn 3 `12781ms`
- `worker-013`: turn 1 `21545ms`, turn 2 `10035ms`

The setup phase now scales much further, but the runtime chat surface still becomes unstable once all users begin interacting concurrently.

### Test-Harness Regression Was Real, But Separate

The blank white page seen immediately after runtime navigation was not the Kaizen auth fix regressing chat. It was a browser handoff issue caused by a no-trailing-slash runtime URL.

Once the scenario navigated to `/runtime/apps/<deployment>/` instead of `/runtime/apps/<deployment>`, the run advanced through:

- Kaizen UI load
- agent creation
- first message send/response

That change explains why the fresh `1`-user smoke succeeded where the earlier rerun stalled.

## Bottom Line

Current status after the latest Kaizen patch set:

- Kaizen workroom create/deploy/auth handoff is much healthier.
- Fresh workrooms can now reach live Kaizen and start real conversations.
- The system still does not support `15` concurrent fresh-workroom users through stable multi-turn chat.

The next debugging target is the runtime conversation path after setup, especially why concurrent sessions degrade into timeouts and `composer not found` once turns begin.

## Artifacts

- Smoke metrics: `uat-bot/data/runs/6f0a4050ccf743f3a054eb275d7ac86c/metrics.jsonl`
- Smoke events: `uat-bot/data/runs/6f0a4050ccf743f3a054eb275d7ac86c/events.jsonl`
- Distinct-user load metrics: `uat-bot/data/runs/ac4a2d83fbcc4fa08277b3c55a1bbd60/metrics.jsonl`
- Distinct-user load events: `uat-bot/data/runs/ac4a2d83fbcc4fa08277b3c55a1bbd60/events.jsonl`
