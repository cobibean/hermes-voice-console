# Portable Hermes Voice Console Design

**Date:** 2026-07-12
**Status:** Awaiting re-approval after product and Hermes-runtime corrections
**Product boundary:** Standalone open-source project

## Summary

Hermes Voice Console is a portable browser control surface with a rich desktop command center and a deliberately simplified mobile companion. Hermes is the agent harness/runtime: it resolves the configured provider and model, assembles context, runs the agent/tool loop, persists sessions, connects memory, enforces approvals, and coordinates delegation. The provider-selected model performs language-model inference. The console supplies authenticated voice and text input, operational visibility, approvals, and spoken output without importing or modifying Hermes source.

The first live reference deployment will run beside the JobHunter Hermes profile on the `hermes-fleet-1` DigitalOcean droplet using Clerk development authentication over the tailnet. Co-location is a deployment choice, not an architectural dependency. The same console must also support a central host connecting to one or more remote Hermes agents over a trusted private network.

OpenAI Realtime conversation mode is deferred. Version one uses a turn-based voice wrapper around the Hermes harness. JobHunter currently selects `gpt-5.5` through Hermes' `openai-codex` provider using Codex OAuth; the console calls Hermes rather than the model directly and pays separately for STT/TTS.

## Goals

- Talk to a Hermes-powered agent from a rich laptop/desktop workspace and a simplified phone interface.
- Preserve Hermes as the sole agent harness/runtime and source of context assembly, tool execution, memory integration, approvals, session persistence, and delegation behavior.
- Use the supported Hermes API Server contract rather than source patches.
- Support push-to-talk, transcript display, streamed run events, approvals, stopping, and TTS playback.
- Authenticate human users with Clerk.
- Retain an optional machine credential for automated smoke tests and programmatic clients.
- Run on the Hermes host or any other trusted host that can reach configured Hermes targets.
- Ship as a reproducible open-source package with portable deployment guidance.
- Produce real-world evidence that can support a focused upstream capability discussion if a generic gap remains.

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
4. The user selects an agent target and an owned conversation; the backend maps it to a Hermes transcript session and server-derived memory scope.
5. The console probes the target and shows distinct console, voice-provider, and Hermes readiness.
6. The user holds the microphone control, speaks, and releases it.
7. The console transcribes the completed utterance and automatically starts a Hermes run.
8. The transcript, agent deltas, tool activity, and run state stream into the interface.
9. Any approval request pauses for an explicit user decision.
10. Completed response sentences may enter TTS progressively while text remains visible.
11. The user may cancel speech without cancelling the agent run, or explicitly request the Hermes harness to stop that run.
12. Reopening the console restores the owned console conversation and recovers active-run state where the Hermes API supports it.

## Architecture

```text
Browser
  <-> HTTPS and WebSocket
Voice Console frontend and backend
  <-> Hermes HTTP and SSE API
One or more Hermes API Server targets
```

### Browser application

The React application has one shared interaction controller and two intentionally different presentation shells. Authentication, target/session identity, conversation history, voice capture, WebSocket transport, runs, recovery, approvals, playback, and errors live above the shells and are never duplicated.

The desktop command center provides:

- persistent agent/profile, connection, conversation, configured-model, audio, and account status;
- a target/conversation rail;
- a central conversation workspace with text and expressive measured-level push-to-talk;
- a persistent run inspector with normalized tool cards, timeline, approvals, recovery, and diagnostics;
- keyboard efficiency, resizable/collapsible information regions, and rich state-driven motion.

The desktop composition should feel like a calm live operations cockpit rather than a generic dashboard card grid. Visual energy must come from real microphone, run, tool, approval, and recovery state—not decorative fake activity.

The simplified mobile companion provides:

- a compact agent/conversation/run header;
- conversation-first content;
- a safe-area-aware sticky text/voice composer;
- on-demand target/session settings, run activity, diagnostics, and approval sheets;
- complete approval, stop, recovery, text fallback, and error visibility with lower persistent density.

Mobile is not the desktop card stack collapsed into one column. Exactly one shell is mounted over the shared controller, so resize and rotation cannot create a second socket or run. Both shells support secure-context microphone behavior, keyboard/screen-reader access, reduced motion, strong focus, and non-hover alternatives.

The browser never receives Hermes API keys, STT/TTS provider secrets, or Clerk server credentials.

### Voice Console backend

The FastAPI service owns:

- Clerk and service-token authentication.
- Deployment authorization policy.
- Configurable Hermes target registry.
- Audio ingestion, bounds, and cleanup.
- Pluggable STT and TTS providers.
- Owned console-conversation identity and authorization.
- Console-owned session authorization and dialogue-continuity compatibility over Hermes SessionDB messages.
- Hermes `/v1/runs` transport and event normalization.
- Approval and cancellation forwarding.
- Run recovery metadata.
- Production frontend serving.

The backend must not import Hermes internals or assume Hermes is installed locally. Target base URLs may use loopback, private LAN, tailnet, or another secured network path.

### Hermes target

Each target is a normal Hermes profile with API Server enabled. The console requires:

- `GET /health`
- `GET /health/detailed`
- `GET /v1/capabilities`
- `GET /v1/models`
- `GET /v1/toolsets`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events`
- `POST /v1/runs/{run_id}/approval`
- `POST /v1/runs/{run_id}/stop`
- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `PATCH /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/messages`

Hermes continues to own provider authentication and model resolution, agent/tool execution, the configured workspace, SessionDB persistence, memory integration, approvals, skills, and delegation. The API Server resolves its own platform toolset rather than inheriting Discord's exact tools. Detached background delivery is not available on this surface; `background=true` delegation falls back to synchronous work inside the active run.

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
6. Backend loads the owned conversation's persisted user/assistant dialogue when needed, emits the final transcript, and starts one Hermes run with explicit conversation history, transcript session identity, and stable memory scope.
7. Hermes run events stream through the backend to the browser.
8. Text and tool events update the response and timeline immediately.
9. Approval events pause for explicit resolution.
10. Completed response sentences may be synthesized and queued without overlapping playback.
11. Cancelled playback drops stale audio; stopping a run is a separate action.
12. Temporary audio is removed unless time-bounded debug retention is explicitly enabled.

## Session and run behavior

- Each owned console conversation maps to a Hermes `session_id`; New Conversation rotates it.
- `X-Hermes-Session-Key` is separate, stable, server-derived, and scoped by target/principal for long-term memory. A fixed `voice-console:job-hunter` scope is permitted only for the single-owner reference deployment.
- V1 intentionally uses a Voice Console-specific long-term-memory identity; it does not silently merge a Clerk user with a Discord or Telegram user/channel.
- Runs does not automatically load prior SessionDB history from `session_id`. The console fetches persisted session messages and sends non-empty user/assistant dialogue as explicit `conversation_history` before subsequent turns.
- The messages API may return a different authoritative `session_id` after Hermes compression. The console atomically updates the internal owned mapping to that resolved ID while keeping the same user-visible conversation.
- Voice and Discord share the Hermes profile, provider/model configuration, workspace, persistence layer, and memory providers, but remain separate platform-scoped sessions and resolve different platform toolsets.
- One active Hermes run is allowed per owned console conversation/Hermes transcript session in version one.
- The microphone is disabled while a run is active.
- Closing or sleeping the browser does not cancel an accepted Hermes run.
- An ambiguous Runs submission with no returned run ID remains locked and is never retried automatically; only the owner can acknowledge the duplicate risk and release it.
- Non-secret run and session identifiers support reconnect and recovery.
- Cancel speech affects playback only.
- Stop run explicitly asks the Hermes harness to interrupt the active run; `stopping` settles as `cancelled`.
- Voice never silently approves a sensitive action.
- Approval copy reflects Hermes' real scope: `session` means the current Run on this API surface, while `always` mutates the target's permanent allowlist and is disabled by default. `always` is never shown when `allow_permanent` is false.

## Failure handling

The UI identifies the failing layer and provides a scoped recovery action:

- **Clerk:** sign-in required, session expired, or user not allowed.
- **Browser:** microphone unsupported or permission denied.
- **STT:** provider missing, timeout, request failure, or rejected audio.
- **Hermes:** target offline, auth rejected, capability missing, run failed, or approval required.
- **TTS:** playback unavailable while text remains usable.
- **Network:** browser-to-console failure versus console-to-Hermes failure.

An STT failure permits retry or text fallback. A TTS failure never loses the answer. Reconnection must not create a duplicate Hermes run. If polling shows an approval wait but the original approval context was lost, approval is disabled and the user may stop the run instead.

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
  -> Hermes harness, API-specific toolset, workspace, sessions, memory
openai-codex provider via existing Codex OAuth
  -> configured GPT-5.5 model performs inference
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
- Run harmless single-turn, multi-turn, and compression/session-rotation checks through the console's real session/run adapters; raw Hermes calls are preflight only.
- Confirm expected harness/profile, configured workspace, memory scope, API-specific tools, configured provider/model, and Codex OAuth without treating API aliases as effective-model proof.
- Verify events, approval, and stop behavior.
- Confirm setup did not modify Hermes source or JobHunter workspace files.

### Gate 3: real voice on the droplet

- Real configured STT and selected TTS provider.
- Desktop command-center push-to-talk, conversation, inspector, streamed run, response, and speech.
- Cancel-speech and stop-run separation.
- Provider failure recovery and audio cleanup.

### Gate 4: remote-device proof

- Rich laptop command center and simplified phone companion over Tailscale HTTPS.
- Clerk sign-in and allowlist enforcement.
- Secure-context microphone behavior.
- Owned-conversation dialogue continuity across devices.
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

On a laptop, an authorized Clerk user gets a rich command center with conversations, streamed agent response, tool/run inspection, approvals, and voice. On a phone, the same user gets a purpose-built simplified companion with conversation-first content, sticky voice/text controls, and on-demand activity/settings sheets. Either experience can continue dialogue with JobHunter, hear the response, approve or deny, stop the run, cancel only speech, and reconnect without duplication or accidental cancellation.

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

After the standalone release is proven, re-check overlapping Hermes browser-voice issues and draft work. Ask maintainers whether a documentation listing or a focused generic API improvement is wanted; do not promise an integration PR. The strongest currently identified generic gap is native Runs history loading from `session_id`. Do not place the console under Hermes `tools/`; it is a user-facing frontend, not an agent-callable tool.
