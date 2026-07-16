# Hermes Realtime Upstream Handoff

This document prepares an upstream conversation. It is not an issue or pull request, and no external write has been made.

## Proposed capability

Add a generic, server-authoritative Realtime session runtime to Hermes that reuses Hermes identity, execution context, approvals, session state, and delegation. The browser carries WebRTC media while Hermes owns sideband policy and tool results. A logical worker-job layer provides stable ownership, controls, evidence, and restart-durable completion delivery above existing asynchronous delegation.

The generic capability does not contain Voice Console presentation code. Product-specific dispatch language, the five-line heuristic, target enablement, and UI remain in the integrating product or platform configuration.

## Local patch lineage

- Upstream implementation base: `0c1adb4877f344af8276d5277871e8056cef3ad5`
- Local branch: `codex/gpt-realtime-session-runtime`
- Tested capability head: `d41e793a355ae1bb9dc2c974d1fd2edc8b6c6a61`
- Scope: 35 files, 12,439 insertions, 46 deletions relative to the base

The local history is organized around these reviewable seams:

1. `cadd93e` proves server-controlled Realtime sessions.
2. `412b551`, `181dfc2`, `98a8cdc`, and `63f4c90` establish and harden routable worker jobs.
3. `d6891b2` extracts the production execution runtime.
4. `076c819` documents and validates configuration.
5. `9e4ea69` adds the durable Realtime v1 runtime and API.
6. `351da78`, `810ac2b`, and `d41e793` add authoritative manual turns, durable approval/command identity, and audio discard.

Before presenting this to maintainers, rebase in a disposable checkout and turn the dependency chain into the smallest independently reviewable series maintainers will accept:

1. Transport-neutral execution context and characterization tests.
2. Generic worker-job state, controls, and async-delegation durability.
3. Realtime contracts, transport, session lifecycle, HTTP composition, and opt-in live smoke.

Do not present a 12k-line feature drop without first explaining these seams and asking maintainers how they prefer the series split.

## Maintainer proposal draft

Hermes currently has the identity, session, tool, approval, and delegation behavior needed for a persistent voice agent, but no server-authoritative Realtime transport. The proposed seam keeps provider handling isolated under `gateway/realtime`, exposes a versioned capability contract, and routes tools through the shared Hermes execution context. It also adds stable worker jobs above async delegation so Realtime rotation or browser reconnection cannot duplicate or orphan logical work.

The browser never receives Hermes or standard OpenAI credentials and cannot authoritatively submit tool results, approvals, or session policy. Existing platforms remain unchanged because the runtime is opt-in and platform-scoped.

Questions for maintainers:

1. Is a generic `gateway/realtime` capability an acceptable ownership boundary?
2. Should transport-neutral execution context land before the Realtime API?
3. Is the worker-job layer appropriate in core, or should it be a maintained adapter/plugin contract?
4. What endpoint and capability naming best fits current Hermes conventions?

## Evidence to attach after refresh

- Exact rebased commit series and diff statistics.
- Focused execution-context, approval, delegation, worker-job, session, HTTP, and Realtime tests.
- Opt-in live GPT-Realtime-2.1 proof with one native direct tool, one GPT-5.6 background worker, approval, barge-in, and completion return.
- Non-voice CLI, Telegram, cron, and API Server regression evidence.
- Supported-pin and current-main compatibility reports.
- Content-safe recovery and security review; no credentials, raw audio, transcripts, responses, or sensitive arguments.

## Upstream and removal decision

Search current upstream issues and pull requests immediately before proposing this work. Ask the owner before opening anything.

If equivalent upstream support ships, validate it against the same contract and live suite, remove the temporary patch, deploy the upstream build through the target-scoped gate, and update the production and rollback pins. If maintainers decline the seam, stop before normalizing a permanent fork and choose explicitly between a maintained adapter/plugin contract, a smaller proposal, or a revised product boundary.
