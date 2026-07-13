# Hermes Voice Console Phase 6 Memory - 2026-07-12

## Session summary

Closed Phase 6 of the approved V1 implementation plan. JobHunter's pinned Hermes API Server is enabled on loopback, and the local console completed real authenticated dialogue, continuity, tool, delegation, stop, and long-context checks without changing Hermes source or making attributable JobHunter workspace edits.

## Remote configuration

- Hermes source remained clean at `7b5ba2054721dde998ed47fd4a0f031955278e99`.
- JobHunter workspace remained at `d7d154edbc184142a6bd25c06173252ab650e34a` with its pre-existing modified and untracked work preserved.
- `hermes-gateway-job-hunter.service` is active and enabled.
- The profile still selects `openai-codex` with `gpt-5.5`; Codex OAuth was logged in during preflight.
- API Server configuration has exactly one occurrence of each required variable and a strong key, with no values recorded here.
- Hermes listens only on `127.0.0.1:8642`; it is not exposed directly to the LAN or tailnet.
- Tailscale Serve configuration was not changed in this phase.
- Permission-preserving rollback backup: `/root/.hermes/profiles/job-hunter/.env.pre-voice-console-20260713T030522Z.bak`.
- Rollback command: `cp -p /root/.hermes/profiles/job-hunter/.env.pre-voice-console-20260713T030522Z.bak /root/.hermes/profiles/job-hunter/.env && systemctl --user restart hermes-gateway-job-hunter.service`.

## Real JobHunter proof

- Read-only preflight proved the required Runs, SSE events, approval response, cooperative stop, session resources, toolsets, models, and delegation-adjacent API surfaces.
- A harmless text turn completed through the console's real service-auth WebSocket, `SessionManager`, `RunCoordinator`, and owned Hermes session.
- Four-turn continuity recalled a nonce, executed `17 * 19 = 323`, and recalled the tool result without another tool call.
- New Conversation created a distinct Hermes session while retaining the same owner-derived memory scope.
- Cooperative stop reached `agent.stopped` after an explicit stop request.
- A harmless approval prompt did not produce an approval event; approval denial is recorded as **not exercised** rather than escalated.
- `delegate_task` with `background=true` emitted matching start/completion events and returned `899`. The parent completed only after the delegate, confirming synchronous fallback rather than detached delivery.
- Four inert context turns of about 11.9K characters each were preserved at exact lengths, acknowledged, and followed by successful first/last marker recall.
- Hermes returned the authoritative session ID. It remained unchanged because GPT-5.5 auto-compaction is raised to 85% of its 272K context, and this safe test did not manufacture roughly 231K tokens solely to force rotation.
- Deterministic tests continue to cover authoritative compression/resume ID adoption and ownership-conflict failure.

## Compatibility fix

- Real Hermes session creation wraps the ID as `session.id`, and session history uses `data` rather than `messages`.
- Updated `backend/voice_console/hermes_client.py` to accept those real resource envelopes while retaining compatibility with the fake target.
- Added a regression case to `tests/backend/test_hermes_client_fake_target.py`.

## Verification

- `.venv/bin/ruff check backend tests` - passed.
- `.venv/bin/pytest` - 38 passed.
- `npm test -- --run` in `frontend/` - 7 files / 19 tests passed.
- `git diff --check` - passed.
- Final remote checks confirmed the pinned clean Hermes source, active/enabled service, loopback-only listener, and one occurrence of every API Server setting.
- Temporary local console port 18787, SSH-forward port 18642, and `/tmp/hvc-phase6.*` state were removed after proof.

## Gotchas and constraints

- Do not claim live auto-compression was triggered; only the real long-context/no-truncation path and authoritative unchanged ID were observed live.
- The Runs API's `background=true` delegation remains synchronous on this transport.
- The JobHunter workspace has unrelated ongoing changes. Preserve them and assess attribution by paths/tool activity, not by assuming a clean tree.
- Phase 7 must deploy beside Hermes under `/opt/hermes-voice-console`, use host networking to reach loopback port 8642, and expose only the console through a new non-conflicting Tailscale Serve endpoint.
