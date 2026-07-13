# Hermes Voice Console Phase 1 Memory - 2026-07-12

## Session summary

Closed Phase 1 of the approved V1 implementation plan. The monolithic backend socket handler and frontend `App` orchestration were split behind explicit seams without changing the working console protocol or visible V1 behavior.

## What changed

- Reduced backend `app.py` to application composition, HTTP routes, static serving, and WebSocket delegation.
- Extracted the voice socket protocol, run lifecycle, connection-local run store, session normalization, and TTS lifecycle into focused modules.
- Reduced frontend `App.tsx` to auth/bootstrap loading, responsive shell selection, and lock handling.
- Extracted the shared console controller, derived visual state, responsive layout hook, desktop/mobile shells, header, run inspector, activity sheet, and shared console content.
- Ensured the controller and its WebSocket/capture/playback ownership live above the responsive branch so exactly one shell mounts without resetting active controller state.
- Added focused backend and frontend architecture-seam tests.

## Files added

- `backend/voice_console/voice_socket.py`
- `backend/voice_console/run_manager.py`
- `backend/voice_console/run_store.py`
- `backend/voice_console/session_manager.py`
- `backend/voice_console/tts_session.py`
- `frontend/src/console/useConsoleController.ts`
- `frontend/src/console/useConsoleLayout.ts`
- `frontend/src/console/viewState.ts`
- `frontend/src/console/DesktopConsole.tsx`
- `frontend/src/console/MobileConsole.tsx`
- `frontend/src/console/RunInspector.tsx`
- `frontend/src/console/ActivitySheet.tsx`
- `frontend/src/console/shared/ConsoleHeader.tsx`
- `frontend/src/console/shared/ConsoleContent.tsx`
- `tests/backend/test_phase1_seams.py`
- `frontend/src/console/console.test.tsx`

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`

## Commands and verification

- `.venv/bin/ruff check backend tests/backend` - passed.
- `.venv/bin/python -m pytest tests/backend -q` - 19 passed.
- `.venv/bin/voice-console fake-e2e` - passed with transcript, run, tool, completion, TTS, and one binary audio chunk.
- `pnpm lint && pnpm typecheck && pnpm test && pnpm build` - passed; 5 Vitest files / 11 tests.
- `git diff --check` - passed.

## Gotchas and constraints

- Desktop and mobile currently share the original content composition intentionally; Phase 4 owns their distinct visual experiences.
- The run store is connection-local by design in this phase; Phase 3 replaces it with durable SQLite-backed history.
- Existing FastAPI/Starlette `httpx` and `websockets.legacy` deprecation warnings remain non-blocking dependency follow-up items.
