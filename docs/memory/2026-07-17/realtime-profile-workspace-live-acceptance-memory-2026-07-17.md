# Realtime Profile and Workspace Live Acceptance Memory - 2026-07-17

## Session summary

- Realtime Hermes now runs as the selected Hermes persona and dispatcher rather than a detached voice model.
- Each Realtime conversation receives an isolated workspace binding derived server-side from Hermes `terminal.cwd`.
- The disposable staging profile used `/Users/cobibean/DEV/hermes-voice-console-github` as its acceptance workspace while keeping profile state and credentials isolated.
- Live desktop acceptance proved the profile `SOUL.md` read, repository search, one `gpt-5.6-sol` worker, spoken result delivery, and transcript restoration after reconnect.
- After owner confirmation that the localhost experience worked, both disposable launch services were stopped and ports `18642` and `18787` were verified closed.

## What we learned

- Loading Soul content into the prompt was not enough: the model needed the context labeled explicitly as authoritative `SOUL.md`, plus a safe tool alias to inspect it on demand.
- Conversation-scoped cwd registration prevents concurrent Realtime sessions from sharing mutable process cwd state.
- macOS case-insensitive paths require filesystem-identity containment checks; lexical `Path.relative_to()` alone can leak case-aliased profile paths.
- A failed initial Realtime bootstrap must clean the lazily-created execution context and cwd binding, while a failed rotation must preserve an existing live conversation.
- The public compatibility contract needs path-free booleans, not path strings or generic primitive passthrough.

## Decisions made

- `terminal.cwd` remains the only authoritative workspace setting. No browser-supplied or duplicate Realtime workspace path was introduced.
- Only exact `read_file("SOUL.md")` is exposed from `HERMES_HOME`; profile listing, traversal, writes, `.env`, `auth.json`, other profile files, mixed-case aliases, and Soul symlinks are blocked.
- Normal relative reads, searches, and delegated coding work remain rooted in the configured workspace.
- Voice Console fails preflight with `Hermes workspace unavailable` when filesystem tools are configured without a valid workspace. Chat-only targets remain compatible.
- The tracked production compatibility manifest and production `~/.hermes` profile were left unchanged.

## Files created or changed

Voice Console commit `75d75314b27048e4a78983fc535d77194abef0a8`:

- `backend/voice_console/realtime/contracts.py`
- `backend/voice_console/fake_target.py`
- `frontend/src/console/useRealtimeSession.test.tsx`
- `tests/backend/test_phase8_recovery_security.py`
- `tests/backend/test_realtime_adapter_phase5.py`
- `docs/visual-qa/2026-07-15/README.md`
- `docs/visual-qa/2026-07-15/final/desktop-realtime-soul-workspace-delegation.png`
- `docs/visual-qa/2026-07-15/final/desktop-realtime-completed-soul-worker.png`

Hermes commit `807c417e949dde80781f3ae1c78cb4c97d8d02e9`:

- `gateway/platforms/api_server.py`
- `gateway/realtime/api.py`
- `gateway/realtime/context.py`
- `gateway/realtime/session_manager.py`
- `tools/file_tools.py`
- `tests/gateway/realtime/test_api.py`
- `tests/gateway/realtime/test_context.py`
- `tests/tools/test_realtime_profile_access.py`

## Source-of-truth docs

- `docs/plans/2026-07-15-gpt-realtime-2-1-hermes-runtime-implementation-plan.md`
- `docs/realtime-rollout-and-release.md`
- `config/hermes-realtime-compatibility.yaml`
- Disposable operator record: `/Users/cobibean/.hermes-staging/voice-console-realtime-20260715-223746/OPERATIONS.md`

## Commands and verification

- Hermes Realtime regression: 102 tests passed.
- Voice Console backend regression: 86 tests passed.
- Frontend: 95 tests passed; TypeScript typecheck and production build passed.
- Independent review found and verified fixes for boolean-only public context, macOS case-alias containment, failed-bootstrap cleanup, and Soul symlink hardening; final review had no remaining findings.
- Disposable candidate rollout gate passed at Hermes `807c417e949dde80781f3ae1c78cb4c97d8d02e9`, including a 98-test focused capability lane.
- Live contract reported `workspace_attached`, `filesystem_tools_available`, and `soul_available` as `true` without exposing paths.
- The live worker used `gpt-5.6-sol`, completed one read-only compatibility analysis, read the Voice Console repository, and wrote no files.
- Production `~/.hermes` fingerprints matched before and after acceptance.
- Shutdown verification: no listeners remained on localhost ports `18642` or `18787`.

## Gotchas and constraints

- Do not infer physical-phone acceptance from desktop browser screenshots. Physical-phone owner acceptance remains pending.
- The disposable profile may remain on disk for audit/rollback context even though its launch services are stopped.
- Upstream Hermes `main` changes rapidly and still requires a deliberate compatibility/rebase lane before replacing the tested candidate.
- Never expose profile paths or credential contents through the browser capability document or test output.

## Recommended next work

- Run the physical-phone acceptance matrix when the product is ready for that gate.
- Before any production rollout, reconcile the Hermes capability branch with freshly fetched upstream `main`, rerun the same target-scoped gate, and preserve rollback evidence.
