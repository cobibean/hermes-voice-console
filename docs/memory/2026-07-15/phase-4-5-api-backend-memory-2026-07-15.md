# Phase 4-5 Realtime API and Backend Memory

**Date:** 2026-07-15

**Status:** Phase 4 and Phase 5 gates passed

## Pinned commits

- Hermes Realtime v1 API: `9e4ea6935f71c38bf598d930978e9ea2526136a8`
- Voice Console backend adapter foundation: `73c6696`
- Control-boundary hardening: `88af1bc`
- Mutation-contract alignment: `a9bbc59`
- Cross-process atomic ledger: `838b7c7`
- Frozen Hermes wire-shape fixture: `2d0d3d98efbeb099104acc42cf7530ff74e21135`

## Phase 4 outcome

- Hermes exposes `contracts.realtime` version `1.0` with explicit media, provider, session, event, tool, worker, approval, routing, retention, timeout, and delivery semantics.
- Session creation returns SDP only after the server sideband acknowledges the complete locked model, tool schema, voice, and turn policy.
- Every session mutation is bound to a stable conversation and durable `client_request_id`; retries return the original typed response, conflicts fail closed, and ambiguous outcomes remain `outcome_unknown` rather than retrying automatically.
- Durable events, snapshots, replay-gap signaling, transcript deduplication, worker state, and the atomic Realtime completion inbox are backed by Hermes state.
- Worker capacity and FIFO claims are atomic across runtimes, including wake-up for queued jobs in the same conversation after another runtime releases capacity.
- Provider event deduplication is conversation-scoped and owner-safe.
- Browser-supplied routing policy cannot override the server-owned Realtime or worker models, tools, voice, persona, or safety identifier.

Independent Phase 4 evidence: 95 focused tests, 366 broader targeted regressions, concurrency/dedupe/restart/schema probes, Ruff, diff checks, and live GPT-Realtime/WebRTC plus real GPT-5.6 worker delivery passed.

## Phase 5 outcome

- Voice Console has an isolated Realtime backend package and dedicated `/ws/realtime` control channel. The legacy `/ws/voice` and Runs coordinator remain unchanged.
- Realtime is target-scoped and disabled by default.
- The proxy requires the exact compatible major and behavioral contract, including endpoint methods and request-result reconciliation.
- All browser requests use operation-specific allowlists. Model, voice, instructions, tools, credentials, and safety policy cannot be supplied by the browser.
- Owner, target, conversation, session, job, request, and command identities are checked at every boundary.
- A content-free local SQLite ledger makes session ownership and request claims atomic across connections and supports restart-safe reconciliation before ephemeral session lookup.
- Upstream responses are endpoint-specific, typed, identity-checked, allowlisted, and recursively redacted before reaching the browser.
- The control socket is snapshot-first, cursor-rebased, bounded, authenticated, and backpressured.
- A fixture pinned to Hermes `9e4ea69` locks every mutation response shape so the fake target cannot hide cross-repository drift.

Independent Phase 5 evidence: 21 focused adapter tests and full `make check` passed with 65 backend tests, 25 frontend tests, lint, typecheck, build, and legacy fake E2E.

## Phase 6 handoff

- Characterize the current controller before extracting behavior.
- Preserve the legacy path in its own media/session adapter.
- Add independent Realtime media and authoritative control clients coordinated by a dedicated session state machine.
- Keep one shared conversation projection and exactly one active transport, peer, microphone capture, and control socket.
- Reconnect from authoritative snapshot, then resume newer event IDs without redispatching restored jobs.
- Keep Realtime behind strict capability preflight with a precise blocked state and explicit legacy fallback.
