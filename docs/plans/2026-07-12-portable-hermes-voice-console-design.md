# Portable Hermes Voice Console Design

**Date:** 2026-07-12
**Status:** Approved
**Product boundary:** Standalone open-source project

## Summary

Hermes Voice Console is a portable, mobile-first browser voice client for any Hermes API Server. Hermes remains the agent, reasoning runtime, tool host, memory owner, and delegation layer. The console supplies authenticated remote voice input, streamed operational visibility, approvals, and spoken output without importing or modifying Hermes source.

The first production deployment will run beside the JobHunter Hermes profile on the `hermes-fleet-1` DigitalOcean droplet. Co-location is a deployment choice, not an architectural dependency. The same console must also support a central host connecting to one or more remote Hermes agents over a trusted private network.

OpenAI Realtime conversation mode is deferred. Version one uses a turn-based voice wrapper around the real Hermes runtime and its existing Codex OAuth provider.

## Goals

- Talk to Hermes from laptop and phone through a secure browser interface.
- Preserve Hermes as the sole agent and source of tool, memory, and delegation behavior.
- Use the supported Hermes API Server contract rather than source patches.
- Support push-to-talk, transcript display, streamed run events, approvals, stopping, and TTS playback.
- Authenticate human users with Clerk.
- Retain an optional machine credential for automated smoke tests and programmatic clients.
- Run on the Hermes host or any other trusted host that can reach configured Hermes targets.
- Ship as a reproducible open-source package with portable deployment guidance.
- Produce real-world evidence suitable for a small upstream Hermes integration PR.

## Non-goals for version one

- OpenAI Realtime speech-to-speech conversation mode.
- Clerk Organizations, team management, or target-level RBAC.
- Bridging directly into an existing Discord or Telegram channel session.
- Multiple simultaneous runs in a single voice session.
- Mid-run steering or queued voice follow-ups.
- Native iOS or Android applications.
- Public exposure of raw Hermes API Server ports.
- Hermes source changes solely to support the console.

## User journey

1. The user opens the Voice Console over HTTPS on a laptop or phone.
2. Clerk restores an existing session or presents sign-in.
3. The console authorizes the Clerk user against the deployment allowlist.
4. The user selects a Hermes target and stable voice-session key.
5. The console probes the target and shows distinct console, voice-provider, and Hermes readiness.
6. The user holds the microphone control, speaks, and releases it.
7. The console transcribes the completed utterance and automatically starts a Hermes run.
8. The transcript, agent deltas, tool activity, and run state stream into the interface.
9. Any approval request pauses for an explicit user decision.
10. Completed response sentences may enter TTS progressively while text remains visible.
11. The user may cancel speech without cancelling Hermes, or explicitly stop the run.
12. Reopening the console restores the stable voice session and recovers active-run state where the Hermes API supports it.

## Architecture

```text
Browser
  <-> HTTPS and WebSocket
Voice Console frontend and backend
  <-> Hermes HTTP and SSE API
One or more Hermes API Server targets
```

### Browser application

The React application provides:

- Clerk sign-in, sign-out, and account controls.
- Target and stable session selection.
- Push-to-talk microphone capture.
- Text-input fallback for accessibility and diagnostics.
- Transcript and streamed assistant response.
- Tool/run timeline and layer-specific diagnostics.
- Explicit approval actions.
- Stop-run and cancel-speech controls.
- Mobile-first layouts and secure-context microphone behavior.

The browser never receives Hermes API keys, STT/TTS provider secrets, or Clerk server credentials.

### Voice Console backend

The FastAPI service owns:

- Clerk and service-token authentication.
- Deployment authorization policy.
- Configurable Hermes target registry.
- Audio ingestion, bounds, and cleanup.
- Pluggable STT and TTS providers.
- Stable voice-session identity.
- Hermes `/v1/runs` transport and event normalization.
- Approval and cancellation forwarding.
- Run recovery metadata.
- Production frontend serving.

The backend must not import Hermes internals or assume Hermes is installed locally. Target base URLs may use loopback, private LAN, tailnet, or another secured network path.

### Hermes target

Each target is a normal Hermes profile with API Server enabled. The console requires:

- `GET /health`
- `GET /v1/capabilities`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}/events`
- `POST /v1/runs/{run_id}/approval`
- `POST /v1/runs/{run_id}/stop`

Hermes continues to own its provider authentication, model selection, workspace, memory, tools, skills, and background delegation.

## Authentication and authorization

### Human authentication

- Use the current `@clerk/react` SDK in the Vite frontend.
- Production UI access requires a valid Clerk session.
- The frontend obtains short-lived Clerk session tokens and sends them to FastAPI.
- FastAPI verifies signature, issuer, expiry, and authorized party using Clerk's supported JWT/JWKS flow.
- No human-facing static-token login form remains in production.
- Clerk tokens are not persisted in application `localStorage`.

HTTP requests use a Clerk bearer token. WebSocket authentication occurs in the encrypted protocol rather than the URL: the first authentication frame contains the current short-lived token, and long-lived connections refresh authentication before expiry. Invalid or expired authentication closes the connection with a specific auth error.

Version one uses a deployment allowlist of Clerk user IDs. Clerk Organizations and roles are deferred.

### Programmatic authentication

An optional server-configured service credential remains available for automated tests, smoke scripts, and programmatic clients.

- It is opt-in and may be disabled entirely.
- It is accepted as an HTTP bearer credential or in the WebSocket authentication frame.
- It never appears in URLs or the human sign-in UI.
- It is compared safely and represented as a distinct `service:<name>` principal in logs.
- It does not auto-approve Hermes actions.

Local unit and fake E2E tests may inject a test authentication dependency. Any unauthenticated development mode must be loopback-only, fail startup on non-loopback binds, and display an explicit warning.

## Voice-turn data flow

1. Browser establishes an authenticated console connection.
2. Console probes the selected Hermes target and required capabilities.
3. Browser sends `recording.start`, then PCM audio frames.
4. Browser sends `recording.stop` when push-to-talk is released.
5. Backend applies duration and size limits, then invokes the configured STT provider.
6. Backend emits the final transcript and starts a Hermes run with the stable session identity.
7. Hermes run events stream through the backend to the browser.
8. Text and tool events update the response and timeline immediately.
9. Approval events pause for explicit resolution.
10. Completed response sentences may be synthesized and queued without overlapping playback.
11. Cancelled playback drops stale audio; stopping a run is a separate action.
12. Temporary audio is removed unless time-bounded debug retention is explicitly enabled.

## Session and run behavior

- Voice uses a stable API Server session such as `voice-console:job-hunter`.
- Voice and Discord share the Hermes profile, workspace, persistence layer, provider, and tools, but remain separate platform-scoped sessions.
- One active Hermes run is allowed per voice session in version one.
- The microphone is disabled while a run is active.
- Closing or sleeping the browser does not cancel an accepted Hermes run.
- Non-secret run and session identifiers support reconnect and recovery.
- Cancel speech affects playback only.
- Stop run explicitly interrupts Hermes.
- Voice never silently approves a sensitive action.

## Failure handling

The UI identifies the failing layer and provides a scoped recovery action:

- **Clerk:** sign-in required, session expired, or user not allowed.
- **Browser:** microphone unsupported or permission denied.
- **STT:** provider missing, timeout, request failure, or rejected audio.
- **Hermes:** target offline, auth rejected, capability missing, run failed, or approval required.
- **TTS:** playback unavailable while text remains usable.
- **Network:** browser-to-console failure versus console-to-Hermes failure.

An STT failure permits retry or text fallback. A TTS failure never loses the answer. Reconnection must not create a duplicate Hermes run.

## Privacy and observability

- Audio is deleted after transcription by default.
- Transcripts and assistant content are excluded from operational logs by default.
- Logs may include timing, provider, target, run ID, error category, and principal type.
- Credentials are redacted from logs, events, diagnostics, and errors.
- Debug audio retention is temporary, explicit, and visibly warned.
- Diagnostics expose configuration presence and connectivity without exposing values.

## Portable deployment contract

The same release supports:

- Console and Hermes on the same host.
- Console on a central host with remote Hermes targets.
- Python/venv installation.
- Container installation.
- systemd, launchd, Docker, or another service manager.
- Tailscale Serve, Caddy, nginx, Cloudflare, or another trusted HTTPS layer.

The application must not hard-code DigitalOcean, Tailscale, Mac Mini paths, root ownership, fixed ports, or loopback-only target URLs.

### JobHunter reference deployment

```text
Laptop or phone
  -> Tailscale HTTPS
Voice Console on hermes-fleet-1
  -> 127.0.0.1:8642 with bearer auth
JobHunter Hermes profile
  -> existing Codex OAuth and GPT-5.5 runtime
```

The Hermes API Server remains loopback-only. Only the Voice Console is exposed through the trusted HTTPS boundary. The console is deployed separately from both the clean Hermes source checkout and the dirty JobHunter operational workspace.

## Verification gates

### Gate 1: deterministic local verification

- Backend tests for protocol, auth, configuration, audio limits, and providers.
- Frontend lint, typecheck, unit tests, and production build.
- Fake Hermes full-turn E2E.
- Clerk HTTP/WebSocket success and failure tests.
- Service-token HTTP/WebSocket tests.
- Secret and browser-storage assertions.

### Gate 2: real JobHunter transport

- Enable API Server through profile configuration only.
- Verify live health and capabilities.
- Run one harmless text-only request.
- Confirm expected profile, workspace, memory, tools, model, and Codex OAuth.
- Verify events, approval, and stop behavior.
- Confirm setup did not modify Hermes source or JobHunter workspace files.

### Gate 3: real voice on the droplet

- Real Whisper transcription and selected TTS provider.
- Desktop push-to-talk, transcript, streamed run, response, and speech.
- Cancel-speech and stop-run separation.
- Provider failure recovery and audio cleanup.

### Gate 4: remote-device proof

- Laptop and phone over Tailscale HTTPS.
- Clerk sign-in and allowlist enforcement.
- Secure-context microphone behavior.
- Stable session continuity across devices.
- Mobile sleep, reconnect, and active-run recovery.
- Mobile approval and stop controls.
- No raw Hermes API exposure.

### Gate 5: portable installation proof

- Fresh Python/venv deployment.
- Fresh container deployment.
- Generic HTTPS proxy documentation.
- Local and remote target examples.
- No environment-specific assumptions.

## Version-one acceptance criteria

From a phone or laptop, an authorized Clerk user can select JobHunter, speak a request, see the transcript, watch Hermes work, hear the response, approve or deny actions, stop the run, cancel speech, and reconnect without duplicating or accidentally cancelling work.

The reference deployment uses the existing supported Hermes API Server and requires no Hermes source modification.

## Open-source and upstream strategy

The standalone repository remains the source of truth.

Before the first public release it must include:

- A clear license and contribution guidance.
- Reproducible quickstarts.
- Architecture, security, privacy, configuration, and deployment documentation.
- CI for backend, frontend, fake E2E, and dependency checks.
- Public-safe secret and artifact audit.
- Versioned release and container image.
- Sanitized real JobHunter smoke evidence.

After the standalone release is proven, submit a small upstream Hermes PR documenting the Voice Console as an API Server frontend/integration. Open a separate upstream design discussion before proposing a larger dashboard or plugin integration. Do not place the console under Hermes `tools/`; it is a user-facing frontend, not an agent-callable tool.
