# Hermes Voice Console

Standalone browser voice console for talking to Hermes agents without patching Hermes source.

This repository is intentionally separate from `NousResearch/hermes-agent` and from the prior `cobibean/hermes-voice-feature` source-patch drop. The old drop remains reference material only; this implementation talks to Hermes through the official API Server surfaces.

## What ships in this repo

- Python FastAPI backend (`backend/voice_console`) with:
  - Clerk human auth, service credentials for automation, and loopback-only development auth;
  - target registry with server-side API key resolution;
  - Hermes API Server capability probing and `/v1/runs` event streaming;
  - approval and stop calls through Hermes API Server;
  - WebSocket voice protocol (`hello`, recording frames, transcript, run events, approval, stop, TTS cancel);
  - recording state machine with turn-id validation, byte cap, wall-clock cap, and buffer clearing;
  - fake STT/TTS providers for deterministic tests plus OpenAI/Groq/faster-whisper STT and Edge/OpenAI/ElevenLabs TTS adapters;
  - console-owned temp audio file manager with ownership, regular-file, symlink, and size guards.
- React/TypeScript/Vite frontend (`frontend`) with:
  - target/session selectors;
  - tap-to-record mic capture using an AudioWorklet PCM16/16k worklet;
  - persistent conversation history with inline tool-call state, plus the full run timeline and diagnostics;
  - accessible approval modal, explicit run stop, and independent speech cancellation;
  - generation-aware playback queue that drops stale/canceled TTS chunks.
- Fake Hermes API Server target and one-command fake E2E (`voice-console fake-e2e`).
- Operator docs under `docs/`.
- `.agent` goal ledger for this implementation.

The current product and deployment source of truth is the [V1 implementation plan](docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md). The older remote-rollout note is retained only as superseded history.

## Quickstart: deterministic fake E2E

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cd frontend && pnpm install && pnpm build && cd ..
voice-console fake-e2e
```

Expected result: JSON with `"ok": true`, run event frame names, and at least one fake TTS binary chunk.

## Run locally with fake providers

Terminal 1:

```bash
source .venv/bin/activate
FAKE_HERMES_API_KEY=fake voice-console fake-target --port 9876
```

Terminal 2:

```bash
source .venv/bin/activate
export VOICE_CONSOLE_SCOPE_SECRET="$(openssl rand -hex 32)"
export FAKE_HERMES_API_KEY=fake
voice-console serve --config config/voice.fake.yaml --targets config/targets.fake.yaml
```

Open `http://localhost:8787`, select the fake target, and use the browser UI. The checked-in fake config uses development auth and cannot start on a non-loopback bind or public URL. Browser microphone access requires `localhost` or HTTPS.

## Real target outline

1. Enable the Hermes API Server adapter on the target agent/profile as a config/service step. Do not patch Hermes source.
2. Set a unique `API_SERVER_KEY` for that Hermes target.
3. Put that key in this console's `.env` under the env var named by `config/targets.yaml` (for example `KNWLDG_API_SERVER_KEY`).
4. Configure a real STT provider (`openai`, `groq`, or `faster_whisper`) and a real TTS provider (`edge`, `openai`, or `elevenlabs`) in `config/voice.yaml`.
5. Build frontend and run `voice-console serve --config config/voice.yaml --targets config/targets.yaml`.
6. Run the manual smoke checklist in `docs/manual-smoke-checklist.md`.

For production investigation, use the content-safe structured event guide in
[`docs/diagnostics.md`](docs/diagnostics.md).

## Verification commands

```bash
source .venv/bin/activate
pytest tests/backend -q
cd frontend
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
cd ..
voice-console fake-e2e
```

`make check` runs the backend, frontend, and fake protocol gates. `make browser-check`
builds the production frontend and runs the real Chromium acceptance suite against
the loopback fake stack.

## Security defaults

- Binds to `127.0.0.1` by default.
- Human deployments use Clerk; automated clients can use a separate service credential.
- Development auth is accepted only with loopback bind and loopback public URL.
- WebSocket credentials are sent only in the first encrypted WSS frame, never in URLs or browser storage.
- Browser JavaScript never receives Hermes API target keys.
- Target API keys are read server-side from env vars referenced in YAML.
- Temp audio is stored in a console-owned directory with mode `0700`; generated files are mode `0600`.
- Remote microphone use should go through HTTPS, preferably Tailscale Serve or a trusted reverse proxy.

## Source-patch boundary

Do not copy the old `/api/voice/ws` Hermes source patch path into this repo as a product direction. The supported architecture is:

```text
Browser mic -> standalone voice console backend -> STT -> Hermes API Server target -> events -> TTS -> browser playback
```

No code in this repository imports or instantiates Hermes agent internals.
