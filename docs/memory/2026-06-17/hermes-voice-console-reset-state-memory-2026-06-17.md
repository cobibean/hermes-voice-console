# Hermes Voice Console Reset State Memory - 2026-06-17

## Session summary

This note captures the current state of `cobibean/hermes-voice-console` for a context reset. The project is built, preserved to GitHub, and still clean/synced after fresh verification on 2026-06-17.

## Current repository state

- Local path: `/root/DEV/hermes-voice-console`.
- GitHub repo: `https://github.com/cobibean/hermes-voice-console`.
- Visibility: private.
- Branch: `main`.
- Product/build verification commit: `3ed6eccf098b2edbe4e64f76c8948d5139c6b4ec`.
- After this reset-memory note is committed, `main` is expected to advance past that product commit with documentation-only memory commits.
- `git status --short --branch`: clean, tracking `origin/main` at the time of verification.
- `git rev-list --left-right --count origin/main...HEAD`: `0	0` at the time of verification.
- GitHub API readback confirmed remote branch `main` pointed at the same SHA before the reset-memory note was committed.

## What is built

Standalone browser voice console for Hermes API Server targets, without patching Hermes source:

- FastAPI backend in `backend/voice_console/`.
- React/TypeScript/Vite frontend in `frontend/`.
- Target registry and Hermes API Server client for capability probing, `/v1/runs`, approval, stop, and event streaming.
- WebSocket voice protocol with recording state/turn validation, byte/time caps, transcript/run/TTS/control frames.
- Fake Hermes target and deterministic `voice-console fake-e2e` path.
- Fake STT/TTS plus real provider adapters for configured environments.
- Console-owned temp audio store with ownership/regular-file/symlink/size guards.
- Operator docs and `.agent` goal ledger.

## Fresh verification run on 2026-06-17

Commands run from `/root/DEV/hermes-voice-console`:

- `source .venv/bin/activate && pytest tests/backend -q`
  - PASS: 15 backend tests passed.
  - Warnings only: FastAPI/Starlette `httpx` deprecation and `websockets.legacy` deprecations.
- `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`
  - PASS: ESLint passed.
  - PASS: TypeScript passed.
  - PASS: Vitest 4 files / 9 tests passed.
  - PASS: Vite production build produced `dist/index.html`, CSS, and JS bundle.
- `source .venv/bin/activate && voice-console fake-e2e`
  - PASS: returned `ok: true`, expected ready/recording/transcript/run/tool/completion/TTS frames, and `binary_chunks: 1`.
- `git diff --check`
  - PASS.
- Tracked-file secret scan
  - PASS after allowlisting obvious `.env.example` placeholder values; no high-risk tracked token/private-key/JWT patterns found.

## Existing evidence/docs to use after reset

- `README.md` — quickstart, fake E2E, local fake providers, real target outline, verification commands.
- `.agent/runs/2026-06-16-standalone-hermes-voice-console/implementation-notes.html` — current human-readable ledger. Its resume section says automated gates are done and manual real smoke is the remaining gate.
- `.agent/runs/2026-06-16-standalone-hermes-voice-console/evidence/final-validation.md` — original validation evidence from 2026-06-16.
- `docs/memory/2026-06-16/standalone-voice-console-memory-2026-06-16.md` — original project memory from the build session.
- `docs/manual-smoke-checklist.md` — the next manual real-smoke checklist.
- `docs/configuration.md`, `docs/target-api-server-setup.md`, `docs/security.md`, `docs/troubleshooting.md`, and `docs/rollback-uninstall.md` — operator docs.

## Remaining gate

The only material remaining gate is real human smoke testing from a real browser/mic environment with:

- reachable Hermes API Server target exposing `/v1/capabilities` and `/v1/runs`;
- target `API_SERVER_KEY` stored in this console's `.env` under the configured `api_key_env`;
- real STT provider configured or local faster-whisper installed;
- real/free-ish TTS provider configured;
- secure browser context (`localhost` or HTTPS/Tailscale Serve);
- speakers/headphones.

Follow `docs/manual-smoke-checklist.md` and record pass/fail for mic, transcript, Hermes run timeline, TTS playback, cancel speech, stop run, approval handling, target auth failure, and provider failure.

## Known caveats

- The environment used for the build/reset verification still does not provide real GUI display or real provider/target credentials, so real browser/mic/STT/TTS/live-target smoke remains intentionally manual.
- `/dev/snd` existed during original validation, but `DISPLAY` and `WAYLAND_DISPLAY` were missing.
- Deprecation warnings from dependencies are non-blocking but worth tracking before packaging as a long-lived service.
- Keep secrets only in `.env`/process env; do not commit target keys, provider API keys, generated session secrets, or auth headers.

## Resume instructions

After reset, if asked to continue this project:

1. Start in `/root/DEV/hermes-voice-console`.
2. Read this note, `README.md`, `.agent/runs/2026-06-16-standalone-hermes-voice-console/implementation-notes.html`, and `docs/manual-smoke-checklist.md`.
3. Do not rebuild or refactor unless asked; the next useful action is arranging/running real manual smoke.
4. If adding deployment/exposure, design the HTTPS/Tailscale Serve/security posture first.
