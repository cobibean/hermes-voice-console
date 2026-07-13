# Hermes Voice Console Phase 3 Memory - 2026-07-12

## Session summary

Closed Phase 3 of the approved V1 implementation plan. Hermes runs and console conversation ownership are now backend-owned and durable across browser disconnects and console restarts, while conversation content remains in Hermes SessionDB and active browser memory rather than the console database.

## What changed

- Added owner-only SQLite state with `0700` directory and `0600` database permissions.
- Added console-owned conversation mappings, unique target/Hermes-session ownership, target-scoped pseudonymous owner keys, and stable server-derived memory scopes.
- Added authenticated session create/list/message proxy routes; arbitrary browser values never bypass owner checks.
- Added Hermes session create/messages and run-status client methods.
- Added explicit dialogue-continuity history injection with bounded read-after-write visibility checks and authoritative compression/resume session-ID adoption.
- Added a process-level `RunCoordinator` that persists submission intent before the Hermes POST, persists accepted run IDs before browser notification, consumes SSE independently of browser sockets, and never reposts on reconnect.
- Added bounded event buffers/subscriber queues, sequence numbers, replay gap snapshots, subscriber-loss handling, terminal cleanup, and process-restart polling reconciliation.
- Added `acceptance_unknown` handling with conversation and owner-target fencing, no automatic retry, and explicit owner acknowledgement.
- Added unrecoverable-after-restart locks that also require explicit owner acknowledgement.
- Added owner checks for subscribe, approve, stop, session access, and risk acknowledgements.
- Added strict persistent-approval filtering, server-side event authorization, clearer run-scoped labeling, and a second UI confirmation before permanent allowlist mutation.
- Added versioned, expiring browser recovery metadata containing identifiers only; terminal state and sign-out clear it.
- Replayed/recovered events restore state without replaying old TTS audio.

## Key files

- `backend/voice_console/run_coordinator.py`
- `backend/voice_console/run_store.py`
- `backend/voice_console/session_manager.py`
- `backend/voice_console/hermes_client.py`
- `backend/voice_console/voice_socket.py`
- `backend/voice_console/fake_target.py`
- `tests/backend/test_run_coordinator_phase3.py`
- `frontend/src/lib/recovery.ts`
- `frontend/src/console/useConsoleController.ts`
- `frontend/src/components/ApprovalModal.tsx`

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`

## Commands and verification

- `.venv/bin/ruff check backend tests/backend` - passed.
- `.venv/bin/python -m pytest tests/backend -q` - 34 passed.
- `.venv/bin/voice-console fake-e2e` - passed through service auth, owned-session creation, transcript, one Hermes POST, run events, TTS, and binary audio.
- `pnpm lint && pnpm typecheck && pnpm test && pnpm build` - passed; 7 Vitest files / 18 tests.
- `git diff --check` - passed.

## Deterministic durability proofs

- Browser subscriber disconnect/reconnect produces exactly one transport start.
- Unauthorized session, resume, approve, stop, and acknowledgement operations fail.
- Ambiguous acceptance remains locked across a different conversation for the same owner/target until explicit acknowledgement.
- A second turn receives the first turn's user/assistant dialogue history.
- Authoritative Hermes session-ID rotation is adopted; ownership conflicts fail closed.
- Process metadata reload reconciles an existing run without reposting.
- A run missing after Hermes restart remains unrecoverable and locked until owner acknowledgement.
- Subscriber backlog produces an explicit bounded gap snapshot.
- SQLite schema/file inspection confirms conversation content and approval payloads are not persisted.

## Gotchas and constraints

- V1 deliberately requires one FastAPI worker; multi-process run coordination remains deferred.
- Content replay is text-only user/assistant dialogue because the audited Hermes Runs adapter does not provide exact prior tool/reasoning replay.
- `previous_response_id` is not used; Hermes SessionDB plus explicit `conversation_history` is the compatibility mechanism.
- A service smoke principal and Clerk human principal derive different target-scoped owners and cannot attach to one another's conversations.
