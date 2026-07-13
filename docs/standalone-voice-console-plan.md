# Standalone Hermes Voice Console Plan

> **Superseded on 2026-07-12.** This file preserves early architecture history but is not an implementation source of truth. Use the [current implementation plan](plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md).

Date: 2026-06-16  
Owner: knwldg for cobibean  
Repo: `/root/DEV/hermes-voice-console`  
Status: plan approved for future implementation prompt; no implementation code yet.

## 1. Decision

Build **Option A — Standalone Voice Console** as a fresh repo outside the Hermes source tree.

The voice console will be its own web app and backend service. It will talk to Hermes agents through official runtime surfaces, primarily the Hermes **API Server** adapter, instead of patching `hermes-agent` source files.

This replaces the prior source-patch direction for fleet use. The old browser-voice drop remains a reference only.

## 2. Reference material

Use this previous work as implementation reference, not as the target architecture:

- Feature-drop repo: `https://github.com/cobibean/hermes-voice-feature`
- Branch: `feat/v2-hermes-native`
- Reference commit: `c20818a15b2a7626ff08f3691b238509e626537c`
- Local drop checkout used during planning: `/root/DEV/review/hermes-voice-feature-c20818a`
- Local scratch-applied Hermes tree used during review: `/root/DEV/review/hermes-agent-c20818a-review`
- Review scratchpad: `/root/DEV/session-scratchpads/hermes-voice-feature-v2-review.md`

Reusable lessons from that drop:

- Browser mic capture and PCM16/16k worklet shape.
- Audio-only WebSocket protocol concepts: `hello`, `recording.start`, binary audio frames, `recording.stop`, transcript event, TTS synth/cancel events.
- Hardening lessons: bounded recording wall-clock, turn-id validation, buffer clearing, cancellation state bounds, TTS file regular/size checks, provider error sanitization.
- Frontend lessons: profile switches, playback queue sequencing, active source cancellation, generation/turn-aware stale event dropping.
- Manual smoke criteria: real secure browser context, real mic, real STT, real TTS, typed and spoken prompt paths, cancellation, provider errors, auth failures.

Things **not** to copy as-is:

- Hermes source patches.
- `/api/voice/ws` inside `hermes_cli/web_server.py`.
- `ChatPage.tsx` modifications.
- Any claim that the feature is part of Hermes core.

## 3. Hermes surfaces to use

Primary integration surface: Hermes API Server platform adapter.

Source evidence from current Hermes reference tree:

- `gateway/platforms/api_server.py:1-23` documents the stable HTTP surface:
  - `POST /v1/chat/completions`
  - `POST /v1/responses`
  - `GET /v1/capabilities`
  - `GET/POST /api/sessions`
  - `POST /api/sessions/{session_id}/chat[/stream]`
  - `POST /v1/runs`
  - `GET /v1/runs/{run_id}`
  - `GET /v1/runs/{run_id}/events`
  - `POST /v1/runs/{run_id}/approval`
  - `POST /v1/runs/{run_id}/stop`
- `gateway/platforms/api_server.py:1126-1203` exposes capability flags, including `run_events_sse`, `run_stop`, `run_approval_response`, `approval_events`, `session_resources`, `session_chat`, and `session_chat_streaming`.
- `gateway/platforms/api_server.py:1544-1727` implements session chat streaming.
- `gateway/platforms/api_server.py:3563-3923` implements structured runs, approval events, run status, and stop support.

Implementation stance:

- The voice console should **probe `/v1/capabilities`** for each target on startup and before first use.
- The voice console should prefer API-server structured run/session surfaces over CLI scraping.
- The console must fail closed with a clear operator message if an agent target lacks API Server or required capabilities.

## 4. Goals

1. Provide a browser voice console for talking to Hermes agents without patching Hermes source.
2. Support multiple Hermes agent targets in one UI.
3. Preserve Hermes as the only agent runtime: the console sends text into Hermes and receives Hermes output; it does not instantiate or fork agent logic internally.
4. Provide high-quality push-to-talk UX: mic capture, transcript confirmation, agent response stream, assistant speech, cancel/stop, status indicators.
5. Use real STT/TTS providers through the console's own provider adapters and config.
6. Ship with tests, fake target server, docs, and manual E2E smoke instructions.
7. Make fleet rollout safe: config-only on Hermes side where possible, no source patches, explicit target registry, no secrets committed.

## 5. Non-goals

- No Hermes source edits.
- No local fork of `hermes-agent`.
- No dashboard `ChatPage.tsx` patching.
- No attempt to be the canonical Hermes session UI.
- No day-one barge-in/full-duplex.
- No unauthenticated public voice endpoint.
- No direct writes to Hermes memory/session DB outside Hermes API Server.
- No bypassing approval flows. If a run needs approval, show the approval request and let the user approve/deny through the API Server approval endpoint.

## 6. Product shape

### User experience

A standalone web app, initially served on `localhost`:

1. User opens the voice console.
2. User selects a target agent/profile from a configured target list.
3. User selects or creates a voice session for that target.
4. User presses and holds a mic button.
5. Browser streams mic audio to the console backend.
6. Backend transcribes audio and shows the transcript.
7. Console sends transcript to the selected Hermes target.
8. UI streams Hermes events: running, text deltas, tool progress, approval requests, completion/error.
9. When assistant output completes, backend synthesizes speech and browser plays it.
10. User can stop/cancel current speech or stop the Hermes run when supported.

### Fleet target examples

`config/targets.example.yaml` should use env-var references for secrets:

```yaml
targets:
  knwldg:
    label: "knwldg"
    base_url: "http://127.0.0.1:8642"
    api_key_env: "KNWLDG_API_SERVER_KEY"
    default_session_key: "voice-console:knwldg"
    preferred_transport: "runs"
    voice:
      tts_voice: "default"
  paperclip:
    label: "Paperclip"
    base_url: "http://100.64.x.y:8642"
    api_key_env: "PAPERCLIP_API_SERVER_KEY"
    default_session_key: "voice-console:paperclip"
    preferred_transport: "runs"
```

`config/voice.example.yaml` should hold non-secret voice settings:

```yaml
server:
  host: "127.0.0.1"
  port: 8787
  public_base_url: "http://localhost:8787"
  auth_required: true

voice:
  stt_provider: "openai"       # openai | groq | faster_whisper | browser_stub_for_tests
  tts_provider: "edge"         # edge | openai | elevenlabs | piper_optional | browser_stub_for_tests
  sample_rate: 16000
  max_recording_seconds: 120
  max_recording_wall_seconds: 180
  max_buffer_mb: 25
  max_tts_text_chars: 8000
  max_tts_audio_mb: 50
  speak_replies_default: false
```

Secrets live in `.env`, never YAML:

```bash
VOICE_CONSOLE_SESSION_SECRET=...
OPENAI_API_KEY=...
GROQ_API_KEY=...
KNWLDG_API_SERVER_KEY=...
```

## 7. Architecture

```text
Browser Voice Console UI
  ├─ AudioWorklet / MediaRecorder mic capture
  ├─ Target/session selector
  ├─ Transcript + event timeline
  ├─ Approval modal
  ├─ Playback queue + cancel controls
  └─ WebSocket to console backend

Standalone Voice Console Backend
  ├─ Auth/session gate for console users
  ├─ Voice WebSocket protocol
  ├─ Recording state machine + bounds
  ├─ STT provider adapters
  ├─ Hermes target registry
  ├─ Hermes API Server client
  │   ├─ capabilities probe
  │   ├─ runs transport
  │   ├─ session chat stream transport
  │   ├─ approval response
  │   └─ stop run
  ├─ TTS provider adapters
  ├─ Temp audio file manager
  ├─ Event log / SQLite session cache
  └─ Static frontend hosting

Hermes Agents
  └─ Existing Hermes API Server adapter per target
      └─ normal Hermes agent loop, tools, approvals, memory, sessions
```

## 8. Transport design

Define an internal interface:

```python
class HermesTransport(Protocol):
    async def health(self) -> TargetHealth: ...
    async def capabilities(self) -> Capabilities: ...
    async def ensure_session(self, requested: SessionRef | None) -> SessionRef: ...
    async def send_turn(self, session: SessionRef, text: str) -> AsyncIterator[HermesEvent]: ...
    async def approve(self, run_id: str, decision: ApprovalDecision) -> None: ...
    async def stop(self, run_id: str) -> None: ...
```

V1 transports:

1. `ApiRunsTransport`
   - Uses `POST /v1/runs`.
   - Streams `GET /v1/runs/{run_id}/events`.
   - Handles `approval.request` via `POST /v1/runs/{run_id}/approval`.
   - Handles stop via `POST /v1/runs/{run_id}/stop`.
   - Maintains local conversation state if needed; passes stable `session_id` and `X-Hermes-Session-Key`.
   - Best for safe external UI control because it exposes approval and stop.

2. `ApiSessionChatStreamTransport`
   - Uses `POST /api/sessions/{session_id}/chat/stream`.
   - Best for persisted session continuity where API Server session resources are enabled.
   - Must be tested against real Hermes to confirm approval behavior; if approval events are incomplete, keep it as secondary/fallback.

Fallback for later, not V1 default:

3. `LocalHermesCliTransport`
   - Spawns `hermes -p <profile>` as a PTY.
   - Useful for local-only emergency fallback but more brittle because output parsing is not structured.
   - Do not make this the main product path unless API Server is unavailable.

## 9. Voice protocol

The browser talks only to the standalone console backend, not directly to Hermes.

Recommended WebSocket frames:

Client to backend:

```json
{"type":"hello","version":1,"target":"knwldg","session_id":"optional","mode":"push_to_talk"}
{"type":"recording.start","turn_id":"vturn_..."}
<binary PCM16 mono 16k chunks>
{"type":"recording.stop","turn_id":"vturn_..."}
{"type":"recording.cancel","turn_id":"vturn_..."}
{"type":"agent.stop","run_id":"..."}
{"type":"approval.resolve","run_id":"...","decision":"once|session|always|deny"}
{"type":"tts.cancel","turn_id":"..."}
{"type":"ping"}
```

Backend to client:

```json
{"type":"ready","target":"knwldg","capabilities":{...},"stt_provider":"...","tts_provider":"..."}
{"type":"recording.started","turn_id":"..."}
{"type":"recording.stopped","turn_id":"..."}
{"type":"recording.discarded","turn_id":"..."}
{"type":"transcript.final","turn_id":"...","text":"...","latency_ms":123}
{"type":"agent.run.started","run_id":"...","session_id":"..."}
{"type":"agent.delta","run_id":"...","delta":"..."}
{"type":"agent.tool.started","run_id":"...","tool":"terminal","preview":"..."}
{"type":"agent.approval.request","run_id":"...","approval":{...}}
{"type":"agent.completed","run_id":"...","text":"...","usage":{...}}
{"type":"tts.start","turn_id":"...","chunk_index":0,"mime":"audio/mpeg"}
<binary TTS audio chunks>
{"type":"tts.end","turn_id":"...","chunk_index":0}
{"type":"tts.complete","turn_id":"..."}
{"type":"error","code":"...","message":"...","recoverable":true}
{"type":"pong"}
```

Protocol rules:

- `hello` is required before all other frames.
- Every recording and TTS turn uses a required validated `turn_id`.
- Turn IDs: max 128 chars, safe charset `[A-Za-z0-9_.:-]`.
- Binary audio frames are accepted only while state is `RECORDING`.
- Recording buffer, byte cap, and wall-clock cap are enforced server-side.
- Agent run and TTS lifecycle are generation-aware; stale events/chunks are dropped.
- Server errors are sanitized; stack traces stay in logs.

## 10. STT/TTS design

Do not import private Hermes internals as the primary path. Implement provider adapters in this repo.

STT V1 providers:

- `openai`: uses the OpenAI transcription API and defaults to `gpt-4o-mini-transcribe`; `whisper-1` remains configurable. Accept `OPENAI_API_KEY` or `VOICE_TOOLS_OPENAI_KEY`.
- `groq_whisper`: optional if `GROQ_API_KEY` is set.
- `faster_whisper_local`: optional local provider behind extras.
- `fake_stt`: test provider.

TTS V1 providers:

- `edge_tts`: default free network provider where acceptable.
- `openai`: paid provider using `gpt-4o-mini-tts` by default, with `tts-1` configurable as a fallback.
- `elevenlabs_tts`: optional provider.
- `fake_tts`: test provider.

Provider hardening:

- Config values are non-secret YAML.
- Secrets come only from `.env` or process env.
- Generated TTS files are written under a console-owned temp/cache directory.
- Stream/delete only console-owned files, not arbitrary provider-returned paths.
- Enforce max TTS input chars and max generated audio bytes.
- Keep provider errors user-readable but secret-safe.

## 11. Frontend design

Tech recommendation:

- Backend: Python FastAPI + `uvicorn` + `websockets`/Starlette WebSocket.
- Frontend: React + TypeScript + Vite, served by backend in production.
- Tests: `pytest` for backend, `vitest`/React Testing Library for frontend logic, Playwright smoke where browser available.

Main UI components:

- `TargetPicker`
- `SessionPicker`
- `VoiceControls`
- `TranscriptPanel`
- `RunTimeline`
- `ApprovalModal`
- `PlaybackControls`
- `SettingsPanel`
- `DiagnosticsPanel`

Frontend state machines:

1. Recording state:
   - idle → connecting → recording → transcribing → sending_to_agent → idle/error
2. Agent run state:
   - idle → running → waiting_for_approval → running → completed/failed/stopped
3. Playback state:
   - idle → synthesizing → speaking → idle/error

Playback requirements:

- Replies are not spoken until final assistant completion by default.
- Speak replies is off by default unless config overrides.
- Queue audio sequentially; never overlap clips.
- Store active `AudioBufferSourceNode` or HTMLAudioElement and stop immediately on cancel.
- Use generation IDs so late TTS chunks from canceled turns cannot play.
- Toggle-off cancels pending synth and active playback.

## 12. Backend modules

Suggested layout:

```text
backend/
  voice_console/
    __init__.py
    app.py                    # FastAPI app factory
    config.py                 # YAML + env loading, redaction
    auth.py                   # console auth/session gate
    protocol.py               # frame parsing, turn-id validation, errors
    voice_session.py           # recording/TTS/agent state machine
    audio/
      capture.py              # PCM/WAV helpers
      limits.py
      tempfiles.py
    stt/
      base.py
      openai.py
      groq.py
      faster_whisper.py
      fake.py
    tts/
      base.py
      edge.py
      openai.py
      elevenlabs.py
      fake.py
    hermes/
      targets.py              # target registry
      api_client.py            # auth, capabilities, sessions
      runs_transport.py
      session_chat_transport.py
      events.py
    storage/
      db.py                    # local SQLite cache/event log
    telemetry.py               # structured logs, timings
frontend/
  src/
    components/
    hooks/
    lib/
    pages/
    styles/
config/
  targets.example.yaml
  voice.example.yaml
tests/
  backend/
  frontend/
  fixtures/
```

## 13. Security and privacy

- Bind to `127.0.0.1` by default.
- For remote use, require HTTPS through Tailscale Serve or a reverse proxy.
- Console UI auth is required unless explicitly disabled for localhost-only dev.
- Use CSRF-safe cookie/session or bearer token for console access.
- Do not expose API server keys to browser JavaScript.
- Browser only talks to the voice console backend.
- Backend talks to Hermes targets with server-side API keys.
- Redact all env values in logs and diagnostics.
- Audio temp files use `0600` where possible and are deleted by default.
- Add retention toggles only for debugging, off by default.
- Do not log full transcripts by default; if event history stores text, make it explicit in config and provide a purge command.

## 14. Testing plan

Backend unit tests:

- Config loading and redaction.
- Target registry env-var resolution.
- API Server capability probe.
- Turn-id validation.
- WebSocket handshake validation.
- Recording byte/wall-clock caps.
- Silent/idle recording timeout.
- Buffer clear after stop.
- STT provider fake success/failure.
- TTS provider fake success/failure.
- TTS temp ownership and size guard.
- Agent event normalization.
- Approval request/resolve flow against fake target.
- Stop flow against fake target.

Frontend tests:

- Recording button state transitions.
- Target/session selector behavior.
- Event timeline rendering.
- Approval modal decisions.
- Playback queue sequencing.
- Cancel drops stale generation chunks.
- Speak replies toggle off stops current playback.
- Error banners for target/auth/provider failures.

Integration tests:

- Fake Hermes API Server with `/v1/capabilities`, `/v1/runs`, `/events`, `/approval`, `/stop`.
- Full fake voice turn: fake PCM → fake STT → fake Hermes run stream → fake TTS → browser receives audio frames.
- Auth rejects unauthenticated console WebSocket.
- Target API key never appears in frontend payloads.

Manual smoke:

1. Run fake target smoke locally.
2. Run real target smoke against one non-critical Hermes profile.
3. Run browser mic test on `localhost`.
4. Run remote HTTPS/Tailscale Serve mic test.
5. Verify cancellation and approval UI.
6. Verify no Hermes source tree changes.

## 15. Deployment plan

Local dev:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cd frontend && pnpm install && pnpm build
voice-console serve --config config/voice.yaml --targets config/targets.yaml
```

Systemd service example:

```ini
[Unit]
Description=Hermes Voice Console
After=network-online.target

[Service]
WorkingDirectory=/root/DEV/hermes-voice-console
EnvironmentFile=/root/DEV/hermes-voice-console/.env
ExecStart=/root/DEV/hermes-voice-console/.venv/bin/voice-console serve --config config/voice.yaml --targets config/targets.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Remote access:

- Prefer Tailscale Serve HTTPS for mic secure context.
- Do not bind public `0.0.0.0` without auth and TLS.
- For fleet agents, prefer each Hermes API Server bound to localhost/Tailscale-only and protected by unique `API_SERVER_KEY`.

## 16. Implementation phases

### Phase 0 — Repo foundation

- Add Python package scaffold.
- Add frontend scaffold.
- Add config examples.
- Add `.env.example`.
- Add Makefile/scripts.
- Add README quickstart.
- Add `.agent` goal ledger for implementation.

Acceptance:

- `python -m pytest` can run placeholder tests.
- `pnpm install && pnpm build` works for starter UI.
- No Hermes source files touched.

### Phase 1 — Target registry and API client

- Implement target config loading.
- Implement server-side API key resolution.
- Implement `/v1/capabilities` probe.
- Implement fake target server for tests.
- Implement target health endpoint in console.

Acceptance:

- Fake target capabilities pass.
- Missing/invalid key fails closed.
- API keys never returned to frontend.

### Phase 2 — Voice WebSocket protocol and recording state machine

- Implement console WebSocket endpoint.
- Implement handshake, turn-id validation, recording start/stop, binary audio accumulation.
- Implement byte and wall-clock caps.
- Implement fake STT provider.

Acceptance:

- Unit/route tests cover malformed frames, no hello, turn mismatch, oversize, timeout, buffer clear.

### Phase 3 — Hermes agent transport

- Implement `ApiRunsTransport` with events, approval, stop.
- Implement `ApiSessionChatStreamTransport` if needed for session-resource continuity.
- Normalize agent events for frontend.
- Maintain local session mapping and conversation metadata.

Acceptance:

- Fake target can stream deltas, tool events, approval requests, completion.
- Console can approve/deny and stop fake runs.

### Phase 4 — STT/TTS providers

- Implement at least one real STT provider and one real/free-ish TTS provider.
- Keep fake providers for tests.
- Implement owned temp audio directory and file guards.

Acceptance:

- Provider tests pass with fakes.
- Real provider smoke is documented and skipped gracefully when keys/deps missing.

### Phase 5 — Frontend voice console

- Implement target/session picker.
- Implement mic controls.
- Implement event timeline.
- Implement approval modal.
- Implement playback queue/cancel.
- Implement diagnostics panel.

Acceptance:

- Frontend tests cover state machines and stale generation cancellation.
- Browser fake smoke shows full fake turn.

### Phase 6 — End-to-end fake smoke

- Add a scripted fake E2E that starts backend + fake target.
- Use Playwright or browser automation where available.
- Verify UI can complete a fake voice turn.

Acceptance:

- One command runs fake E2E locally.

### Phase 7 — Real manual smoke

- Configure one real Hermes target API Server.
- Configure real STT/TTS provider.
- Run browser mic on localhost or HTTPS/Tailscale Serve.
- Confirm full mic → transcript → Hermes → assistant text → TTS playback.
- Confirm approval/stop behavior if the target can produce a safe approval prompt.

Acceptance:

- Manual smoke notes include target, command, provider, browser, pass/fail, and remaining limitations.

## 17. Definition of done

The standalone voice console is done for V1 when:

- It runs from this repo without modifying Hermes source.
- It can connect to at least one real Hermes API Server target.
- It can complete a real browser mic → STT → Hermes agent → TTS playback loop.
- It handles target auth failures, provider failures, cancellation, and stop cleanly.
- It includes backend tests, frontend tests, fake E2E, and manual smoke docs.
- It includes operator docs for configuring target agents and voice providers.
- It includes a rollback/uninstall path.
- It records that API Server enablement is a config/service step, not a source patch.

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hermes API Server not enabled on a target | Make target health fail clearly; provide config steps; do not fallback silently to source patching. |
| API Server session vs runs behavior differs | Implement capability probe and test against live target early; keep transport interface narrow. |
| Approval events incomplete in session chat stream | Prefer `/v1/runs` for approval-capable mode. |
| Browser mic blocked on HTTP remote | Use localhost for dev and Tailscale Serve HTTPS for remote. |
| STT/TTS cost | Default to explicit provider config; show provider and warn before long recordings. |
| Stale audio after cancel | Use generation IDs and queue tests. |
| Secret leakage | Server-side env resolution only; redaction tests; no API keys in browser payload. |
| Feature creep into fleet control plane | Keep V1 to voice console + target registry; no agent administration UI. |

## 19. Immediate next step

Use `docs/prompts/build-goal.md` as the slash prompt to start the full implementation goal in this repo.
