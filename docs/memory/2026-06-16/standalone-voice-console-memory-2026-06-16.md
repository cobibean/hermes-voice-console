# Standalone Hermes Voice Console Memory - 2026-06-16

## Session summary

Built `/root/DEV/hermes-voice-console` into a standalone browser voice console that talks to Hermes targets through API Server `/v1/runs` rather than patching Hermes source. The repo now has a FastAPI backend, React/Vite frontend, fake Hermes target, fake E2E, tests, docs, and `.agent` goal ledger.

## What we learned

- The standalone companion architecture can fully exercise voice-console behavior through public HTTP/WebSocket/SSE-style surfaces without importing Hermes internals.
- The V1 capability gate must require the full run/approval/stop contract, not just `run_events_sse`.
- Frontend audio must wait for backend `ready` and `recording.started` before sending PCM chunks.
- Push-to-talk release during connection needs a stop-request flag so recording does not continue after an early release.
- Provider-generated temp audio must be cleaned up on provider exceptions/cancellations, not only after successful streaming.

## Decisions made

- Kept the old `cobibean/hermes-voice-feature@feat/v2-hermes-native` drop as reference only.
- Implemented fake STT/TTS and fake target paths so automated verification works without real provider credentials.
- Left real browser/mic/STT/TTS smoke as the final manual gate because this environment lacked provider credentials, real target key, and GUI display.

## Files created or changed

- Backend: `backend/voice_console/`, `pyproject.toml`, `scripts/fake_e2e.py`, `tests/backend/`.
- Frontend: `frontend/src/`, `frontend/package.json`, `frontend/pnpm-lock.yaml`, `frontend/public/voice/pcm-worklet.js`.
- Config/docs: `.env.example`, `config/voice.fake.yaml`, `config/targets.fake.yaml`, `README.md`, `docs/*.md`, `docs/systemd-service.example.ini`.
- Ledger: `.agent/GOALS.md`, `.agent/runs/2026-06-16-standalone-hermes-voice-console/`.

## Commands and verification

- `pytest tests/backend -q` — 15 passed.
- `pnpm lint && pnpm typecheck && pnpm test && pnpm build` — passed; frontend tests 4 files / 9 tests.
- `voice-console fake-e2e` — passed with `ok: true` and one fake TTS binary chunk.
- Secret scan — passed with no high-risk token patterns.
- `git diff --check` — passed.
- Browser fake smoke: loaded `http://127.0.0.1:8788`, unlocked with test token, connected/probed fake target, diagnostics showed `Connected: yes` and ready event.

## Gotchas and constraints

- Port `8787` was already occupied during final local browser smoke, so the fake browser smoke used a temporary config on `8788`.
- Manual real smoke requires a browser secure context, real target API Server key, and real STT/TTS provider configuration.
- Do not store actual API keys/tokens in repo docs, YAML, ledger evidence, or frontend state.

## Remote preservation

Created and pushed the repo to `https://github.com/cobibean/hermes-voice-console` as a private GitHub repository. Remote `main` was read back and matched the local commit after push.

## Recommended next work

Run `docs/manual-smoke-checklist.md` from a real browser/mic environment with a reachable Hermes API Server target and configured STT/TTS providers. Capture pass/fail for transcript, run timeline, playback, cancel, stop, approval, auth failure, and provider failure.
