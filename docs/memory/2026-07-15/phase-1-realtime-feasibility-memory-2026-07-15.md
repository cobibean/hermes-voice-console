# Phase 1 Realtime Feasibility Memory

**Date:** 2026-07-15

**Status:** Hard Gate A passed

## Pinned evidence

- Hermes implementation base: `0c1adb4877f344af8276d5277871e8056cef3ad5`
- Verified proof commit: `cadd93e6a0cddbd29c9b66abe85c862eeb4e4ffa`
- Hermes proof branch: `codex/gpt-realtime-session-runtime`
- Voice Console branch: `codex/gpt-realtime-hermes-runtime`

## Verified product path

- GPT-Realtime-2.1 became the active, server-controlled Realtime session model.
- An audio-only WebRTC peer connected successfully in the live proof. This is observed behavior, not a documented OpenAI compatibility guarantee.
- GPT-Realtime issued a native named `delegate_work` function call.
- Hermes started one real, non-blocking `gpt-5.6-sol` background child through its existing delegation substrate.
- GPT-Realtime completed a second harmless tool call while the worker remained active.
- Hermes automatically detected the persisted worker completion and returned it through the active sideband without manual result publication.
- The OpenAI and Hermes credentials remained server-side.

## Gate protections

- Policy activation waits for authoritative `session.updated` and fails closed.
- Session creation is idempotent under concurrent retries and fenced against stale generations.
- Provider tool calls execute once per provider call ID.
- Approval decisions are server-issued, owner-bound, generation-bound, expiring, and one-shot, including concurrent duplicate rejection.
- Speech interruption does not cancel durable worker execution.
- Realtime rotation preserves logical delegation identity and completion delivery.
- Provider-facing errors are sanitized and provider calls use the documented hangup endpoint.
- Session-owned tasks are cancelled, awaited, and evicted while durable workers remain independent of ephemeral media sessions.

## Independent verification

- Phase 1 review: `PASS`
- Focused and selected regression suite: `86 passed`
- Realtime-focused tests: `26 passed`
- Ruff: passed
- `git diff --check`: passed
- Live OpenAI WebRTC, model-tool, real-worker, concurrent-conversation, and automatic-completion smoke: passed

## Production extraction constraints

- Keep all control and tool authority on the Hermes sideband. A browser data-channel fallback may be unused and untrusted if provider compatibility requires it.
- Replace the proof callback bridge and private delegation entry point with the transport-neutral Hermes execution context.
- Replace proof polling with the native completion subscription used by the production worker-job layer.
- Add byte bounds to assembled context, lifecycle-aware ledger retention, bounded pending approvals/results, and explicit long-worker timeout semantics.
- Re-prove interrupt and Realtime rotation against the production integration, not only the deterministic proof provider.

Voice Console Realtime remains disabled until the compatible production contract and product integration pass their later gates.
