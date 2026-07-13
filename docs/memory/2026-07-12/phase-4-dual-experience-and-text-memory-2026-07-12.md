# Hermes Voice Console Phase 4 Memory - 2026-07-12

## Session summary

Closed Phase 4 of the approved V1 implementation plan. The console now supports typed and voice turns through one durable run path, presents a desktop command center and a simplified mobile companion as distinct experiences, and includes a sanitized live-target smoke command.

## What changed

- Added one bounded input validator shared by STT transcripts and typed text.
- Added `text.submit` / `text.accepted`; typed input clears only when the backend confirms an accepted Hermes run.
- Disabled text composition while a run or acknowledgement lock is active.
- Built a desktop three-region command center with conversation rail, working conversation/composer, voice controls, and live run inspector.
- Built a separate mobile experience with compact status header, settings sheet, conversation surface, activity sheet, floating talk control, and sticky composer.
- Kept exactly one controller/socket above the responsive shell boundary.
- Added owned-conversation creation/selection in both shells.
- Reframed responses as agent output and operator-configured provider/model labels rather than describing Hermes as the model.
- Improved approval presentation with normalized facts, explicit run scope, filtered permanent scope, and second confirmation.
- Improved pointer capture and keyboard operation for push-to-talk; full cancel/discard semantics remain Phase 8.
- Added `voice-console smoke` with read-only health/detailed-health/capabilities/toolsets/models checks.
- Required both `--allow-run` and explicit `--text` for write smoke; output includes timings and event names but no prompt, response, keys, or target URL.
- Extended deterministic fake E2E to execute a voice turn followed by a context-aware typed turn.

## Key files

- `backend/voice_console/smoke.py`
- `backend/voice_console/protocol.py`
- `backend/voice_console/voice_socket.py`
- `frontend/src/console/DesktopConsole.tsx`
- `frontend/src/console/MobileConsole.tsx`
- `frontend/src/console/shared/Composer.tsx`
- `frontend/src/console/useConsoleController.ts`
- `frontend/src/styles.css`
- `tests/backend/test_smoke_phase4.py`
- `frontend/src/console/console.test.tsx`

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`

## Commands and verification

- `.venv/bin/ruff check backend tests/backend` - passed.
- `.venv/bin/python -m pytest tests/backend -q` - 37 passed.
- `.venv/bin/voice-console fake-e2e` - passed voice plus typed follow-up; typed turn received prior Hermes dialogue context.
- `pnpm lint && pnpm typecheck && pnpm test && pnpm build` - passed; 7 Vitest files / 19 tests.
- Desktop/mobile structural test proves distinct shell information architecture over the same controller.
- Sanitized read-only and double-opt-in write smoke tests passed.
- `git diff --check` - passed.

## Gotchas and constraints

- The smoke models endpoint verifies configured aliases/routes, not the effective inference model used for a run.
- Mobile/desktop browser-level interaction proof belongs to Phase 7/9 on the deployed HTTPS origin.
- Real microphone level visualization, discard-on-cancel, hallucination filtering, and upgraded speech defaults belong to Phase 8.
