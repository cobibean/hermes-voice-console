# Phase 8 — Recovery, security, and upgrade gate

Date: 2026-07-15

Production status: disabled

Voice Console branch: `codex/gpt-realtime-hermes-runtime`

Hermes capability branch: `codex/gpt-realtime-session-runtime`
Pinned and minimum tested Hermes commit: `d41e793a355ae1bb9dc2c974d1fd2edc8b6c6a61`

## Gate result

The implemented automated Phase 8 gate is green for the pinned capability, proxy, storage, upgrade-blocking, and browser recovery cases listed below. Phase 8 as a whole remains pending the explicit live/browser race cases under "External and human gates not claimed here." Realtime remains disabled, no target was deployed, and no production configuration was changed.

The console fails before media startup when the target omits the Realtime contract, advertises the wrong contract major, lacks a required endpoint or feature, uses browser rather than server authority, or does not advertise `gpt-realtime-2.1`. The production pin passes the source and focused runtime suites. The local `main`/`origin/main` reference at `0c1adb4877f344af8276d5277871e8056cef3ad5` has no Realtime contract and is correctly classified as unsupported rather than silently accepted.

No unresolved high-risk security finding was found. One medium browser-recovery hardening gap was fixed: session storage now rejects unbounded or path-like identifiers, fractional or negative cursors, future timestamps, and any expiry other than the fixed two-hour window.

## Compatibility matrix

| Lane | Expected result | Evidence | Result |
| --- | --- | --- | --- |
| Minimum supported | Compatible | Same exact commit as pin; parsed 1.x contract/API/HTTP surface, runtime capability probe, 92 focused Realtime tests | Pass |
| Production pin | Compatible | Active Hermes checkout exactly `d41e793`; parsed contract, runtime capability preflight, focused and non-voice regression suites | Pass |
| Current main, non-production | Compatible or blocked before startup | Local tracking ref `0c1adb4` lacks `gateway/realtime/contracts.py` | Pass: blocked |
| Realtime disabled | Legacy-only behavior | Manifest remains `enabled: false`; disabled-target backend test | Pass |
| Model unavailable | Block before media startup | Contract matrix removes model/provider advertisement | Pass: blocked |

Run the compatibility check with:

```bash
HERMES_REALTIME_REPO=/absolute/path/to/hermes-agent-realtime make realtime-upgrade-gate
```

The script is deliberately read-only. It requires the Hermes checkout to be exactly pinned with no tracked or untracked changes, parses that commit's contract, API methods, and HTTP surface, obtains capabilities from the checked-out runtime, runs the Voice Console compatibility parser including a model-unavailable negative probe, and executes the 92-test Hermes Realtime suite. A dirty checkout, different minimum commit, or newly capable `main` fails until it is validated in its own disposable checkout. The command never switches a running Hermes checkout or touches an active agent.

## Automated recovery matrix

| Boundary | Deterministic evidence |
| --- | --- |
| Capability absent, wrong major, missing features/endpoints, model unavailable | `test_phase8_capability_and_model_failure_matrix_fails_closed`; `test_capability_negotiation_is_strict_and_preserves_rich_contract`; `test_disabled_target_fails_closed` |
| Credential and upstream failure sanitization | `test_browser_surfaces_never_expose_target_credentials`; `test_upstream_arbitrary_error_body_is_never_reflected`; Hermes tool/sideband redaction tests |
| SDP before/after acceptance and audio-only browser authority | `realtimeClient.test.ts`: audio-only peer, superseded stream, post-SDP release, ICE abort |
| Sideband loss with media alive | Hermes `test_sideband_loss_freezes_new_actions_and_result_replays_after_rotation` |
| Media loss with durable workers alive | Realtime rotation/result-routing tests plus browser release tests; workers are conversation-owned rather than call-owned |
| Control reconnect and cursor resume | `realtimeControlClient.test.ts`: snapshot-before-replay, reconnect from cursor, failed-socket fencing; backend replay-gap snapshot test |
| Duplicate/out-of-order events | `conversationProjection.test.ts` event-ID dedupe; Hermes durable event and transcript projection tests |
| Duplicate function calls and client mutations | Hermes provider-call ledger test; console atomic request claims, cached delete/approval/worker-command tests |
| Browser close during legacy conversation/run | Playwright close/reload and pre-run-ID recovery scenarios |
| Browser close during active Realtime worker, pending approval, or undelivered completion | Durable snapshot/no-redispatch and completion-projection layers are covered; exact browser-level timing cases remain pending and are not claimed as closed |
| Voice Console restart | content-free SQLite mapping/request ledger reopen and worker-command lookup restart tests |
| Realtime rotation while worker runs | Hermes automatic result route to replacement-call tests |
| Hermes restart | durable event, request, approval, and worker state tests; running attempts become explicit `outcome_unknown` rather than being resumed blindly |
| Approval expiry/double/wrong owner | Hermes expiry and concurrent duplicate approval tests; console owner isolation and latched submission tests |
| Refinement/cancel/completion races | Revisioned worker command and terminal/stale rejection primitives pass; exact reversible/irreversible/approval-wait/cancellation/completion browser timing matrix remains pending |
| Cancel speech vs cancel worker | console interrupt test proves worker remains running; worker cancel uses a separate command path |
| One-worker default/fan-out | contract requires default fan-out 1, max concurrency 1, max fan-out 1, FIFO per conversation |
| Legacy and non-voice regression | Voice Console legacy fake E2E/Playwright suite; 356 representative Hermes gateway tests passed, 21 environment-gated skips |
| Content-safe browser persistence | recovery metadata allowlist tests and executable built-asset scan |

## Security evidence

`scripts/realtime_security_gate.py` is a defense-in-depth heuristic over production browser assets and non-test browser source after the frontend build. It fails on provider credential markers, OpenAI-style secrets, source maps, dynamic/aliased/unapproved Web Storage writes, direct IndexedDB/cookie/Cache API writes in application source, or content fields in recovery persistence. The only approved application storage write is `hvc.recovery.v1`; save constructs its seven fields explicitly and load rejects non-exact key sets. Hostile tests inject transcript, response, tool arguments, API-key, token, and Authorization extras across save and stored-JSON paths.

Additional authoritative-boundary proof:

- Browser input cannot select persona, voice, tools, safety identity, worker model, approvals, or tool outputs.
- SDP and control bodies have independent byte limits, JSON-object checks, identifier grammar, and typed generation/revision checks.
- HTTP and WebSocket Realtime routes reuse the existing authentication, exact origin checks, target selection, and conversation owner key.
- Direct tools are advertised by the server allowlist; raw `delegate_task` is not exposed.
- Sideband loss freezes new execution and moves the visible control state to degraded/reconnecting.
- Public compatibility output is a strict allowlist and strips internal URLs, prompts, credentials, and unknown fields.

## Verification commands and results

- Voice Console focused Phase 8 backend tests: 6 passed, including hostile browser-asset and empty-contract upgrade lanes.
- Voice Console frontend suite: 17 files / 94 tests passed, including exact recovery-key allowlisting and hostile extra-field persistence cases.
- Hermes focused `tests/gateway/realtime`: 92 passed.
- Hermes representative API Server/platform/profile/Telegram/Discord/voice regression: 356 passed, 21 skipped because those cases are explicitly environment-gated.
- Browser artifact security gate: passed.
- Upgrade gate: passed with pinned checkout exact and current main blocked.
- Full `make check`: passed (backend, lint, 17 frontend files / 94 tests, production build, browser security audit, and fake E2E).
- Full `make browser-check`: 8 Playwright scenarios passed against the polished desktop/compact/mobile UI. Screenshot evidence is stored under `docs/visual-qa/` by the visual acceptance slice.

One transient manual-discard transport failure was triaged as a possible race instead of being ignored. The exact backend discard/restart case passed 20 consecutive runs, and all four frontend discard/reconnect cases passed 20 consecutive runs (80 assertions across those repeated files). No deterministic failure reproduced, so no timing workaround was added; the staging telemetry gate must still watch for a real 502 recurrence.

Chromium's synthetic microphone twice produced an explicit zero-byte capture late in the full serial browser suite while the same test passed alone. The Playwright case now retries only that exact `no audio captured` outcome, at most twice, without weakening the product's empty-audio rejection. Five focused repetitions and the final 8-case suite passed after the harness correction.

## External and human gates not claimed here

These checks require the later staging/acceptance phase and are not replaced by deterministic tests:

- A real invalid/expired OpenAI Realtime credential, actual provider rate limit, and account-level model-access denial.
- Provider-side partial acceptance or regional network faults against a real call.
- Browser close/reopen at the exact instants an active Realtime worker is running, an approval is pending, and a completion is durable but not yet delivered.
- Spoken refinement at the exact reversible, irreversible, approval-wait, cancellation, and completion-race boundaries.
- Desktop and phone Human Gate B, including interruption feel, rotation/background behavior, visual quality, and owner approval.
- A freshly fetched future upstream `main`; this gate records the local tracking ref and must be rerun after any fetch/update.
- Production deployment, target enablement, rollback rehearsal, and live telemetry.

Phase 9 must keep the target-scoped flag off until the owner completes the real desktop/mobile acceptance flow.
