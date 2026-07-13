# Portable Hermes Voice Console V1 Implementation Plan

**Status:** Awaiting repository-owner re-approval after current-docs and live-host review.

**Approval gate:** Do not implement this plan until the repository owner approves this revision.

**Execution model:** Implement normally. The primary agent may delegate bounded work to subagents when parallel research, implementation, or independent review is useful, and may handle cohesive work directly. Do not invoke a skill to implement this plan.

**Source of truth:** This plan and the companion design supersede `docs/remote-rollout-next-steps.md` and `docs/standalone-voice-console-plan.md` for future work. The README continues to describe the currently implemented token-authenticated prototype until implementation begins.

## Outcome

Ship a standalone browser console with two intentionally different presentations: a rich, interactive desktop command center and a deliberately simplified mobile companion. Both presentations use the same authenticated session, voice, text, run, approval, stop, playback, and recovery engine.

The first live proof will run beside JobHunter on the `hermes-fleet-1` droplet. The application must remain deployable on another Linux host, a Mac, or a container host that can reach a supported Hermes API Server.

OpenAI Realtime is not part of V1. Hermes is the agent harness: it assembles context, calls the configured model through its provider layer, runs the agent/tool loop, connects memory, persists sessions, and coordinates delegation. The model selected through that provider performs the language-model inference. On JobHunter today, the profile selects `openai-codex` authenticated by Codex OAuth and model `gpt-5.5`; the console does not call that model directly. The console pays separately for its configured speech-to-text and text-to-speech APIs.

## Evidence Refreshed on 2026-07-12

### Local repository

- Backend: 15 pytest tests pass.
- Frontend: lint, typecheck, 9 Vitest tests, and the Vite production build pass.
- The current “fake E2E” is a backend WebSocket protocol integration test. It does not launch or test the React application.
- Whole-tree Ruff is not green: it reports 12 existing findings. The earlier plan incorrectly treated Ruff as a passing baseline.
- `backend/voice_console/app.py` currently owns app composition, HTTP routes, WebSocket protocol, STT, Hermes runs, approvals, stop, and TTS in one 311-line function. More behavior should not be added there without extracting responsibilities.
- `frontend/src/App.tsx` is a 280-line workflow component, and `styles.css` has only one responsive rule that stacks the same cards below 780px. The current UI implements neither a desktop command center nor a purpose-built simplified mobile experience.

### Live JobHunter host, inspected read-only over Tailscale

- Tailnet peer `job-hunter` is online and reachable from this Mac.
- Linux hostname: `hermes-fleet-1`.
- Hermes gateway service: `hermes-gateway-job-hunter.service`, active and enabled in root's user-systemd scope.
- Active Hermes source: clean commit `7b5ba2054721dde998ed47fd4a0f031955278e99`, reported up to date.
- JobHunter workspace: `/root/DEV/job-hunter` at `d7d154e`; it has existing modified and untracked files that must be preserved.
- Hermes profile: `/root/.hermes/profiles/job-hunter`.
- Provider authentication: `openai-codex` is logged in for the same root profile/service user.
- `API_SERVER_ENABLED`, `API_SERVER_KEY`, `API_SERVER_HOST`, and `API_SERVER_PORT` are absent.
- Nothing is listening on 8642.
- Docker 29.1.3 and Docker Compose 2.40.3 are installed and active.
- Host Node and pnpm are absent. The reference deployment should therefore use a multi-stage container rather than requiring host JavaScript tooling.
- Port 8787 is occupied by an unrelated root-owned review application:

  ```text
  /root/.hermes/hermes-agent/venv/bin/python
    -m uvicorn scripts.review_app.app:app
    --host 0.0.0.0 --port 8787
  ```

- Existing Tailscale Serve routes on HTTP 80 and HTTPS 443 proxy their root path to that application. They must not be changed or replaced.
- Local ports 8788, 8790, and 9443 were free at inspection time. The JobHunter reference deployment reserves `127.0.0.1:8788` for the console and tailnet-only HTTPS port 9443 for Tailscale Serve, subject to one final pre-deploy recheck.

## What the Current Hermes Contract Actually Supports

The compatibility baseline is capability-driven. Commit `7b5ba205` is the audited reference, not a hard-coded version requirement.

The console requires these live capabilities and endpoints:

- bearer authentication;
- `GET /health`;
- `GET /health/detailed`;
- `GET /v1/capabilities`;
- `GET /v1/models`;
- `GET /v1/toolsets`;
- `POST /v1/runs`;
- `GET /v1/runs/{run_id}`;
- `GET /v1/runs/{run_id}/events`;
- `POST /v1/runs/{run_id}/approval`;
- `POST /v1/runs/{run_id}/stop`;
- `GET /api/sessions`;
- `POST /api/sessions`;
- `GET /api/sessions/{session_id}`;
- `PATCH /api/sessions/{session_id}`;
- `GET /api/sessions/{session_id}/messages`;
- `features.run_submission`;
- `features.run_status`;
- `features.run_events_sse`;
- `features.run_stop`;
- `features.run_approval_response`;
- `features.session_resources`;
- `features.session_key_header == "X-Hermes-Session-Key"`;
- `runtime.mode == "server_agent"`;
- `runtime.tool_execution == "server"`;
- `runtime.split_runtime == false`.

`audio_api` and `realtime_voice` are expected to be false. Audio is deliberately owned by this standalone console.

At the audited commit, the machine-readable capability is `features.run_approval_response`. One prose paragraph in the Hermes API documentation still calls it `run_approval`; implementation must trust the live capability document and endpoint map, not that stale prose label.

### Corrected Hermes assumptions

- Hermes is the harness/runtime, not the LLM. “JobHunter” means the configured Hermes profile/agent. `openai-codex` is its current provider/auth path, and `gpt-5.5` is its currently configured model. The model performs inference; Hermes supplies context, tools, memory, control flow, persistence, and delegation around it.
- API sessions use the same profile, provider/model configuration, workspace, session database, and memory backing as JobHunter, but they resolve the API-specific `hermes-api-server` toolset. They are not the Discord toolset or Discord conversation.
- The default API toolset includes terminal, files, web, browser, memory, session search, and `delegate_task`. It excludes interactive `clarify`, `send_message`, and Hermes' own TTS tool.
- V1 must inspect the real `/v1/toolsets` response before a write test instead of claiming tool parity from config alone.
- The console does not send a `model` override in V1. Hermes resolves the profile's configured model/provider, session overrides, and any configured fallback. `/v1/models`, capability `model`, and run `model` expose API/profile or routing aliases, not proof of the effective inference model. The UI labels the live read-only profile evidence as “configured primary” and never claims a specific model executed a run unless Hermes adds an authoritative field.
- `/v1/runs` uses `session_id` as correlation and persistence identity; it does not automatically load prior session messages into the next model call. Multi-turn conversation requires explicit history handling.
- A stable `session_id` is also not sufficient for long-term-memory scoping. Every run must send a server-derived `X-Hermes-Session-Key` that is stable for the console owner and target.
- Stop is cooperative. The transport returns `stopping` and ultimately settles as `cancelled`; the console should not invent a Hermes `stopped` status.
- Hermes owns a run after `POST /v1/runs` succeeds, independently of the browser and independently of the SSE subscriber.
- The Hermes event stream is not replayable after its SSE handler disconnects. The console must own and maintain that SSE connection. If it breaks, the console polls run status and never re-posts the prompt.
- `/v1/runs` does not provide an idempotency guarantee. An ambiguous POST timeout is shown as “acceptance unknown” and is never retried automatically.
- Terminal run status is retained for roughly one hour in the audited implementation. Unconsumed event transport expires after roughly five minutes.
- Detached background delegation is not solved by the current Runs API. Because the API platform has `supports_async_delivery = false`, Hermes downgrades `delegate_task(background=true)` to synchronous execution: the parent run remains active until delegate summaries return. V1 may exercise and display proven `delegate_task` start/completion, but it must not claim post-run background work, asynchronous delivery, or nested subagent progress. Later detached work needs polling/jobs, the TUI Gateway, or a generic upstream API addition.
- Delegates inherit the parent provider/model/toolset unless Hermes delegation configuration overrides them; they do not inherit the parent's memory context. Live JobHunter currently has no fallback provider, delegation model/provider override, or explicit API Server toolset override, so current delegates inherit the configured `openai-codex`/`gpt-5.5` path and default API toolset. Treat this as refreshed configuration evidence, not a portable assumption.

The SSE limitation above comes from the audited handler, which removes the run's only event queue when a subscriber disconnects. This is stricter than the API guide's optimistic attach/detach wording. The implementation therefore treats polling as recovery for status and final output, not as a way to recover missed event deltas.

### Why V1 uses Runs

Hermes exposes several plausible transports, but none satisfies the complete V1 workflow by itself:

- Chat Completions is stateless and requires the caller to resend history; it has no run-level approval, cooperative stop, or durable run-status handle.
- Responses preserves full tool-call history through `previous_response_id`, but the Responses result is not the Runs control surface used for owner-authorized approval, stop, and recovery.
- Session `chat/stream` loads SessionDB history natively, but it is a single request stream without the Runs ID/status/approval/stop lifecycle required for a browser that may sleep or disconnect.
- Runs provides immediate acceptance, polling, approval, and stop. Its missing automatic SessionDB history load is handled by the explicitly tested compatibility adapter below.
- The TUI Gateway exposes richer interactive controls, including clarify, steering, delegation status, and session branching. It is deferred because V1 is intentionally built around Hermes' language-agnostic HTTP target contract rather than owning or embedding a TUI Gateway process. Keep the transport boundary narrow enough to evaluate a later TUI Gateway adapter without rewriting either UI shell.

Hermes' Jobs API is a candidate for later scheduled or detached work. It is not used to simulate inline nested subagent progress in V1.

## Product and Security Decisions

### Standalone boundary

```text
Laptop or phone browser
  -> HTTPS and authenticated WebSocket
Hermes Voice Console frontend + FastAPI backend
  -> loopback/private HTTP and SSE with server-held bearer key
Hermes API Server and JobHunter harness/profile
  -> session/context assembly, agent loop, memory, tools, approvals, delegation
openai-codex provider authenticated by Codex OAuth
  -> configured model performs language-model inference
```

No Hermes Python package is imported by the console. A missing capability stops the rollout; it is not a reason to patch Hermes source silently.

### Domain language used in code and UI

- **Harness:** Hermes Agent software and its API/gateway runtime.
- **Agent/profile:** JobHunter, the configured Hermes profile with its workspace and behavior.
- **Provider:** `openai-codex`, which supplies model access through Codex OAuth for this profile.
- **Model:** currently `gpt-5.5`; it performs language-model inference and may change through Hermes configuration.
- **Run:** one agent turn executed by the Hermes harness.
- **Voice Console:** the independent authenticated control surface and speech adapter.

UI copy says “JobHunter response,” “agent run,” or “Hermes harness status” according to what it actually means. It must not label Hermes as the LLM or imply the console itself owns the model.

### Desktop command center and mobile companion

V1 has two intentionally designed browser experiences over one shared interaction engine. It is not mobile-first, and mobile is not the desktop page stacked into one column.

The shared interaction engine owns authentication, target and session identity, conversation history, the WebSocket, microphone capture, typed input, run recovery, transcript and response state, tool events, approvals, stopping, TTS playback, and error classification. Desktop and mobile never implement separate transport, run, authentication, or recovery logic.

#### Desktop web workspace

Desktop is the primary rich experience:

- A persistent command bar shows the selected agent/profile, connection state, current conversation, truthfully reported model information, audio state, and account controls.
- A left rail contains target selection plus owned conversation creation, selection, and renaming.
- The center workspace contains the persistent conversation stream, streaming agent response, text composer, and an expressive tap-to-record surface driven by real microphone levels.
- A persistent right inspector contains run state, normalized tool cards, event timeline, approval context/actions, recovery state, and diagnostics.
- Real agent state drives useful motion and feedback: listening, transcribing, acceptance unknown, running, using a tool, waiting for approval, stopping, speaking, reconnecting, completed, cancelled, and failed.
- Desktop adds keyboard efficiency, resizable/collapsible information regions, and hover detail, but no safety-critical action depends on hover or a shortcut.

At widths from 768 through 1179 CSS pixels, this remains the desktop workspace but the right inspector becomes a drawer. At 1180 pixels and above, the full three-region workspace remains visible.

#### Simplified mobile experience

Mobile preserves the complete safe workflow with lower information density:

- A compact header shows agent/profile, connection, conversation, and current run state. Target and conversation selection live in a settings sheet.
- Conversation and current response remain the main surface.
- A safe-area-aware sticky composer contains a large tap-to-record control, text fallback, recording/speaking state, cancel-speech, and the current run lock.
- Tool/run activity is summarized inline; full activity opens in a bottom sheet.
- Approval uses a focused full-screen dialog or sheet with understandable context and least-destructive action visible without raw JSON.
- Stop run remains explicit while active and is visually separated from release-to-send and cancel-speech.
- Diagnostics are available on demand rather than occupying permanent space.
- Rotation, the virtual keyboard, browser backgrounding, and interrupted touch gestures must not duplicate a turn or stop an accepted run.

“Simplified” removes persistent density, not safety or capability. Mobile retains approval context, deny/approve, explicit stop, recovery, text fallback, and scoped error visibility.

The mobile shell is selected at 767 CSS pixels or below, plus phone-sized coarse-pointer landscape viewports through 932 pixels. Pointer capability changes target sizing and gesture treatment, not available functions. Exactly one shell is mounted at a time, above one controller that survives resize and rotation without creating a second socket or run.

The tested layout query is `(max-width: 767px), (max-width: 932px) and (orientation: landscape) and (any-pointer: coarse)`. Everything else uses the desktop shell; widths from 768 through 1179 pixels use its compact inspector-drawer variant.

Both experiences use at least 44-by-44 CSS-pixel primary touch targets, visible keyboard focus, semantic status announcements, strong contrast, forced-colors support, and reduced-motion behavior. Streamed tokens and every tool delta are not individually announced to assistive technology; state transitions are announced politely and with throttling.

#### Visual and interaction direction

Desktop should feel like a calm live operations cockpit built around conversation, voice, and agent activity—not a grid of generic dashboard cards. State transitions may reshape emphasis, motion, color, and inspector focus, but decoration never pretends that work is happening. The microphone visualization is measured, the tool timeline is evidence-backed, and the active approval or recovery state becomes visually dominant when it needs a decision.

Mobile uses the same visual language but a quieter composition: conversation and the current action stay primary, secondary operational detail moves into sheets, and motion is shorter and less spatially complex. These are two compositions of one product, not two brands and not two independent applications.

#### Shared derived presentation state

Both shells render one derived view state over the lower-level recording, transport, run, approval, and playback states:

```text
disconnected | connecting | ready | listening | transcribing |
acceptance_unknown | running | using_tool | waiting_for_approval |
stopping | speaking | reconnecting | completed | cancelled | failed
```

The derived state prevents contradictory presentation without erasing the underlying independent state machines.

This is the primary presentation state, not the entire state model. Explicit secondary flags and inspector regions may simultaneously show facts such as an active run while progressive speech is playing. The precedence rules and concurrent indicators are shared and tested rather than inferred separately by each shell.

#### Approval presentation

- Normalize approval context into understandable fields such as tool, operation, command/path/host, reason, and consequence.
- Keep additional sanitized detail behind disclosure; raw JSON is never the only explanation.
- Desktop presents approval prominently in the inspector and an accessible dialog when immediate input is required.
- Mobile uses a focused full-screen dialog/sheet.
- Initial focus lands on the heading or least-destructive action, focus remains contained, and focus returns logically. Escape never approves: it either performs a clearly disclosed deny action or closes the presentation while a persistent blocked-run alert remains.
- `deny` blocks the pending action.
- `once` allows only that pending action.
- Hermes' wire-level `session` choice is labeled **Allow for this run** because the audited Runs adapter keys approval state by `run_id`; it does not cover the console conversation or a later turn.
- Hermes' wire-level `always` choice writes the matched approval pattern into the target profile's permanent command allowlist/config. It appears only when the event says `allow_permanent: true` and deployment policy explicitly enables persistent approvals. The JobHunter reference deployment defaults that policy off. When enabled, the UI names the persistent mutation, de-emphasizes it, and requires a second confirmation.
- The API event currently includes `always` in its generic choices list even when `allow_permanent` is false. The console must honor the stricter flag and never offer or send `always` in that case.

### Human and machine authentication

- Human production access uses Clerk.
- The first `.ts.net` tailnet proof uses a Clerk development instance. Clerk production requires an owned domain and DNS, so a plain Tailscale hostname must not be labeled a production Clerk deployment.
- A later public production deployment uses an owned domain, a Clerk production instance, and an explicit HTTPS routing design.
- An optional service token remains available for programmatic tests. It never appears in a human UI, URL, browser storage, transcript, or log.
- Local interactive fake mode uses an explicit development principal with a prominent warning. Startup requires both a loopback bind and loopback `public_base_url`; deployment docs forbid placing this mode behind Tailscale or another proxy. The process cannot reliably discover every external proxy, so the plan must not claim automatic proxy detection.
- Service mode is programmatic-only and renders an explanatory browser screen rather than a secret input.

The frontend first loads an unauthenticated `/api/public-config` document containing only:

```json
{
  "auth_mode": "clerk",
  "clerk_publishable_key": "pk_test_public_value",
  "public_base_url": "https://tailnet-hostname:9443"
}
```

The publishable key is public. Issuer, allowed user IDs, authorized origins, service tokens, target keys, and provider keys remain server-only. Runtime public config keeps one container image portable across Clerk instances.

`clerk_publishable_key` is required only when `auth_mode` is `clerk`; it is `null` for service or loopback-development mode. The frontend initializes Clerk only after reading a valid Clerk-mode document.

### Clerk verification contract

Backend verification returns an internal `AuthContext` containing the principal and token expiry. It must:

- accept only RS256;
- fetch keys from the configured instance JWKS with a five-second network timeout and cache;
- validate exact HTTPS issuer plus `exp`, `nbf`, `iat`, and `sub`;
- allow five seconds of clock skew;
- validate `azp` against a non-empty exact origin allowlist;
- return 401/4401 for invalid authentication;
- return 403/4403 for a valid but disallowed Clerk user;
- bind reconnect, run subscription, approval, and stop to the same principal;
- compare service tokens with `hmac.compare_digest`.

The browser WebSocket cannot send an Authorization header. It connects to `/ws/voice` with no query parameters, then sends an authentication frame over WSS. The server checks the WebSocket `Origin`, limits pre-auth frame size and authentication time, and accepts `hello` only after authentication.

For the JobHunter reverse-proxy deployment, Uvicorn trusts forwarded scheme/host headers only from loopback, where Tailscale Serve connects. FastAPI validates HTTP and WebSocket `Host` against explicit configured hosts derived from `public_base_url` plus intentional loopback development hosts; production never uses a wildcard. Browser Clerk/development connections require an exact allowed `Origin`. Programmatic service clients may omit `Origin`, but a supplied origin must still be allowed. Tailscale identity headers are not an authentication substitute for Clerk or the service credential.

Clerk tokens normally live about one minute and `getToken()` is cached. A fixed refresh interval is not sufficient. The server emits `auth.expiring` about 15 seconds before JWT expiry. The browser answers using `getToken({ skipCache: true })`. The refreshed token must identify the same principal. Without a valid refresh, close at token expiry plus five-second skew; the backend-owned Hermes run continues and the browser recovers on reconnect. Service and development principals do not refresh.

Use Clerk Core 3's current React surface, including `<Show when="signed-in">` and `<Show when="signed-out">`; do not implement removed `SignedIn` or `SignedOut` components.

### Privacy and browser storage

- Audio is deleted immediately after transcription unless short-lived debug retention is explicitly enabled.
- Operational logs omit transcript text, response text, approval arguments, tokens, and credentials.
- The browser may store only versioned recovery metadata: target name, console conversation ID, run ID, last sequence, `savedAt`, and `expiresAt`.
- Recovery metadata is schema-validated, time-limited, cleared on terminal state and sign-out, and treated as untrusted on the server.
- No JWT, service token, transcript, response, approval payload, or provider value enters `localStorage` or `sessionStorage`.
- The interface visibly states that spoken output is AI-generated.

## Session, Memory, and Conversation Continuity

Hermes exposes three different identities that the console must not conflate:

- **Console conversation ID:** an owner-authorized record used by the desktop/mobile session picker.
- **Hermes `session_id`:** the persisted transcript/correlation identity in the JobHunter SessionDB.
- **`X-Hermes-Session-Key`:** the stable long-term-memory scope threaded into the harness and memory provider.

### Console-owned session authorization

The console SQLite store maps each console conversation to target, Hermes session ID, pseudonymous owner key, title, memory-scope key, and timestamps. It contains no conversation content. The browser never supplies an arbitrary Hermes session ID that the backend trusts.

- Create Hermes sessions through `POST /api/sessions` with opaque `hvc_` IDs.
- Treat the returned Hermes session ID as authoritative; if it differs from the requested opaque ID, persist only the returned value before starting a run.
- List/select only sessions present in the console's owner mapping.
- Proxy metadata, titles, and messages only after checking principal ownership.
- Desktop exposes recent conversations in its left rail; mobile exposes the same owned list in a sheet.
- Service smoke tests use a separate service-owned session and cannot attach to a Clerk user's conversation.
- V1 does not bridge or expose Discord sessions.

### Short-term conversational context

Current `/v1/runs` does not auto-load SessionDB history from `session_id`. After authorizing and locking the stable console conversation, and before every run after the first, the console:

1. retrieves the owned session's messages from `GET /api/sessions/{session_id}/messages`;
2. while holding the stable owned console-conversation lock, adopts the response's authoritative `session_id`, which may be a compression/resume successor, by atomically updating that conversation's mapping;
3. fails closed if that resolved ID conflicts with another owner mapping;
4. builds text conversation history from non-empty user and assistant messages;
5. submits that history in `conversation_history` with the resolved Hermes session ID and the new `/v1/runs` input;
6. lets the completed turn persist back into that resolved JobHunter SessionDB session.

Call this layer the **dialogue continuity compatibility adapter**. The audited Runs handler currently reduces explicit conversation history to role/content pairs, so V1 sends only non-empty user/assistant text and does not claim exact replay of prior tool-call structures, reasoning items, or nested delegate progress. Prior final agent answers still carry the usable conversational result.

Before accepting a subsequent turn, the adapter must confirm that Hermes SessionDB exposes the prior completed user/assistant turn. It may use a short bounded read-after-write retry, but it must fail visibly rather than silently omit a turn or invent a parallel transcript.

The real JobHunter gate must prove:

- a unique nonce stated in turn one can be recalled in turn two;
- a follow-up can refer to the result of a harmless prior tool-using turn;
- New Conversation rotates transcript history while the stable memory key remains valid;
- long history reaches Hermes' own context/compression behavior without the console truncating it silently;
- a compression/resume successor returned by the messages API replaces the internal Hermes session ID without changing the user-visible console conversation or losing ownership.

Failure stops the rollout. If exact tool-call replay or native session resume is required, treat automatic Runs history loading as a focused generic upstream API gap rather than copying Hermes internals or persisting a parallel transcript in the console.

`previous_response_id` is not the V1 continuity mechanism because Runs responses do not return a chainable Responses API ID.

### Long-term memory scope

The server derives the memory key; it is never editable in the browser. The portable default computes a stable HMAC-SHA256 owner key from `(target, principal kind, principal subject)` using `VOICE_CONSOLE_SCOPE_SECRET`, then places its first 32 hex characters beneath a configured target prefix. The same pseudonymous owner key authorizes console sessions and runs without storing the raw Clerk user ID in SQLite. The single-owner JobHunter deployment may explicitly configure a fixed `voice-console:job-hunter` scope. A multi-user deployment must not share that fixed scope.

V1 intentionally uses a Voice Console-specific memory scope. It does not claim automatic long-term-memory identity with a Discord or Telegram user/channel. Cross-channel identity would require an explicit administrator-owned mapping and a separate privacy review.

New Conversation rotates the Hermes `session_id` while retaining the owner's stable memory scope. This mirrors short-term transcript reset versus long-term memory continuity.

### Content residency

Conversation content resides in Hermes' existing SessionDB and in the active browser view. The console database stores only ownership and recovery metadata. The console may transiently fetch history to construct the next run but does not duplicate it on disk or in logs.

## Run and Reconnection Design

Extract a single-process `RunCoordinator` from the socket handler. It owns accepted Hermes runs, one Hermes SSE connection per active run, authorization, bounded in-memory event fan-out, status reconciliation, and persistent non-content metadata.

### Ownership and locking

- Lock key: `(target_name, console_conversation_id)`, which remains stable when Hermes rotates a compression/resume session ID.
- Enforce a unique `(target_name, hermes_session_id)` mapping so two console conversations or principals cannot point at the same Hermes transcript session.
- Run owner: the authenticated principal's server-derived pseudonymous owner key.
- Only the owner may subscribe, approve, or stop.
- One FastAPI worker is required in V1. Multi-process coordination is deferred.

### Stored run metadata

Persist to a console-owned SQLite database:

- nullable run ID, absent only while submission acceptance is unknown;
- target name;
- console conversation ID, current Hermes session ID, and stable memory session key;
- pseudonymous owner key;
- turn ID;
- status;
- last sequence;
- created, updated, and terminal timestamps;
- failure category without response content.

Keep event payloads, transcript text, assistant text, and approval details in bounded memory only. Create the SQLite state directory as `0700` and database as owner-only. Bound every subscriber queue, retain at most 250 normalized events per active run, expire terminal metadata after two hours, clean up background tasks on FastAPI lifespan shutdown, and emit an explicit `run.snapshot`/gap event when a reconnect asks for events older than the retained buffer. `acceptance_unknown` is non-terminal and is never auto-expired or auto-unlocked; it remains visible to its owner until explicit acknowledgement.

### Acceptance and recovery rules

1. Validate typed or transcribed text through one input validator.
2. Before sending bytes to Hermes, persist a content-free local turn record and acquire the owned conversation lock with status `submitting`.
3. Start the run once. Never retry an ambiguous Hermes `POST /v1/runs`.
4. An explicit non-202 response is a definite rejection. A connection failure known to occur before request transmission is a local transport failure. A timeout/reset after transmission may have begun is `acceptance_unknown` because Runs has no idempotency key, run listing, or discoverable client turn ID.
5. `acceptance_unknown` keeps the local conversation lock and adds an uncertainty fence on `(target, owner)` across reconnect and process restart, preventing a new conversation from bypassing the warning. The UI explains that the run may still be executing and offers no automatic retry or approval/stop control without a run ID.
6. The default action is **Keep locked**. Only the authenticated owner may send `run.acceptance_unknown.acknowledge` for that `turn_id`, after confirming **Acknowledge risk and unlock**. This releases the conversation lock and owner-target fence but does not stop any unknown Hermes work. A later resubmission is a separate explicit turn with a second confirmation; session history is never treated as proof that retry is safe.
7. Persist an accepted run ID before attempting to notify the browser.
8. Start the backend-owned Hermes SSE consumer immediately.
9. Every normalized event carries `run_id`, `turn_id`, and a console sequence.
10. Browser disconnect removes only that subscriber and its TTS work. It does not stop or detach the Hermes consumer.
11. Reconnect lookup uses authenticated `(principal, target, console conversation)` first, so recovery works even if the browser disconnected before receiving `agent.run.started`. Client-provided `resume_run_id` is only an optimization.
12. If the console-to-Hermes SSE breaks, poll `GET /v1/runs/{id}` to terminal and reconcile final output/status. Never re-post.
13. Whenever polling reports `waiting_for_approval` but the console lacks the original approval context—whether from SSE loss or console restart—prohibit blind approval. Explain that the decision details cannot be verified and offer explicit stop.
14. After a console-process restart, reload non-content metadata and poll Hermes status. Intermediate deltas cannot be recovered.
15. If Hermes itself restarted and no longer knows the run ID, mark the run unrecoverable, require explicit user acknowledgement before releasing the local lock, and never recreate the turn automatically.
16. Normalize Hermes `stopping` and `cancelled` accurately in both Python and TypeScript.

## Speech Provider Decisions

- Default OpenAI STT: `gpt-4o-mini-transcribe`, which OpenAI documents as more accurate than original Whisper. Keep `whisper-1` configurable for comparison or fallback.
- Rename the provider abstraction from `OpenAIWhisperProvider` to `OpenAISttProvider` because it supports more than Whisper.
- Default first-test TTS: configurable `gpt-4o-mini-tts` through `/v1/audio/speech`, with `tts-1` retained as a fallback. Re-check live model availability during deployment because catalog/deprecation labels can change independently of the endpoint contract.
- Request a low-latency browser-supported format and propagate the actual MIME type through every TTS frame. Do not construct typeless browser blobs.
- Split input well below both the speech endpoint's character cap and the model token cap.
- Filter known empty-audio/Whisper hallucination phrases before starting Hermes.
- Progressive TTS copies the upstream UX behavior, not Hermes source code: strip markdown and `<think>` content, buffer complete sentences with a minimum useful length, synthesize sequentially, and never overlap playback.
- Replayed recovery events restore text but do not replay old audio.
- Cancel speech clears current and queued TTS only. Stop run is a separate Hermes action.
- Drive the recording visualization from measured microphone input levels; do not ship a decorative fake waveform. Show elapsed time and the configured maximum.
- Recording is a two-tap toggle in both shells: Start recording, then Send recording. Native button semantics provide mouse, touch, Enter, and Space operation. Page hide during an unsubmitted recording or explicit cancel discards it through a real `recording.cancel` protocol action.
- Provide a keyboard-operable equivalent and visible focus without making a global single-character shortcut fire while typing.
- Unlock browser audio playback during a user gesture and provide a visible play fallback when autoplay policy still blocks speech.
- On `visibilitychange` and `pageshow`, re-evaluate Clerk expiry, socket state, recording state, and active-run recovery. A frozen mobile tab may lose its socket without stopping the backend-owned run.

## Implementation Sequence

### Phase 0 — Establish a truthful clean baseline

**Files:** existing backend/tests only.

- Fix the 12 existing Ruff findings without changing behavior.
- Re-run pytest, Ruff, frontend lint/typecheck/tests/build, and the backend protocol integration.
- Record the baseline counts in the pull request or implementation handoff.

**Gate:** all claimed local checks are actually green before feature work.

### Phase 1 — Extract architecture seams before adding behavior

**Files:**

- Keep `backend/voice_console/app.py` for composition, lifespan, HTTP routes, and static serving.
- Create `backend/voice_console/voice_socket.py` for connection protocol and socket limits.
- Create `backend/voice_console/run_manager.py` and `run_store.py` for run ownership and metadata.
- Create `backend/voice_console/session_manager.py` for owned Hermes sessions, history compatibility, and memory-scope derivation.
- Create `backend/voice_console/tts_session.py` for per-connection speech queuing.
- Add focused tests under `tests/backend/` for each module.
- Keep `frontend/src/App.tsx` responsible for public-config/auth gating and mounting one console controller.
- Create `frontend/src/console/useConsoleController.ts` as the single owner of the voice client, capture, playback, sessions, recovery, lower-level state, and commands.
- Create `frontend/src/console/viewState.ts` for the shared derived presentation state.
- Create `frontend/src/console/useConsoleLayout.ts` for the tested shell boundary.
- Create `frontend/src/console/DesktopConsole.tsx` and `MobileConsole.tsx`.
- Create shared conversation, composer, voice-state, approval, run-status, and error primitives.
- Create desktop `RunInspector` and mobile `ActivitySheet` presentations over the same normalized events.

First move existing behavior with no product change. Then implement against these boundaries. Avoid another all-in-one rewrite of `create_app` or `App`. Exactly one shell is mounted, and neither shell creates its own WebSocket.

**Gate:** existing fake protocol behavior still passes after extraction; resizing between test layouts keeps one controller and does not create a second socket.

### Phase 2 — Implement config, Clerk, service auth, and WebSocket security

**Backend files:** `config.py`, `auth.py`, `app.py`, `voice_socket.py`, `protocol.py`, `pyproject.toml`, example config/env files, new auth/socket tests.

**Frontend files:** `main.tsx`, `App.tsx`, `lib/api.ts`, `lib/voiceClient.ts`, `lib/types.ts`, Clerk test helpers, component/client tests, package and lockfile.

- Add `PyJWT[crypto]==2.13.0`, reinstall the editable environment, and add current `@clerk/react` 6.12.2.
- Model `clerk`, `service`, and loopback `development` auth explicitly.
- Implement runtime `/api/public-config`.
- Require `VOICE_CONSOLE_SCOPE_SECRET` for server-derived owner/memory keys, document rotation consequences, and keep it separate from Clerk, service, Hermes, and speech-provider credentials.
- Add optional non-secret target metadata for `configured_provider_label` and `configured_model_label`; display it only as operator-configured primary information, never as effective-run proof.
- Add `allow_persistent_approvals`, default false, as deployment policy. It can only narrow Hermes' event-level `allow_permanent`; it cannot widen it.
- Remove target `base_url` from browser DTOs and sanitize capability data before exposing it.
- Replace URL/static-token auth with HTTP bearer and encrypted WS auth frames.
- Implement exact Host and Origin checks, WSS-outside-loopback, frame-size limits, auth timeout, expiry-driven refresh, principal continuity, and content-free audit logs using principal kind plus a shortened pseudonymous owner key rather than raw Clerk IDs.
- Clerk mode renders sign-in/account controls. Development mode renders the console with a warning. Service mode renders a programmatic-only notice.
- Delete the human token form and all token storage helpers.
- Keep checked-in interactive fake config loopback-development. The backend protocol integration creates its own temporary service-mode config.

**Gate:** Clerk and service HTTP/WS success/failure tests pass; browser bundles and storage contain no console secret or Clerk token.

### Phase 3 — Implement the durable Hermes transport before text or voice polish

**Files:** `hermes_client.py`, new session/run manager and store modules, fake target, app/socket wiring, backend tests, frontend session/run state and recovery modules and tests.

- Add `get_run()` and exact capability/runtime checks.
- Add Hermes session create/list/get/patch/messages client methods, authoritative compression/resume ID adoption, and console-owned session authorization.
- Derive the memory key on the server, send both transcript `session_id` and `X-Hermes-Session-Key`, and never trust either from an arbitrary browser value.
- Before subsequent Runs turns, fetch owned Hermes session messages, verify the prior completed turn is visible with a bounded retry, and build the explicit user/assistant text history required by the dialogue continuity compatibility adapter.
- Split start-run from event consumption so the coordinator persists acceptance before browser notification.
- Keep `RunCoordinator` dependent on the existing transport protocol/adapter rather than API-specific calls from the UI or socket layer; `ApiRunsTransport` is the V1 implementation.
- Implement owner-checked subscribe, approve, and stop.
- Add bounded buffers, subscriber backpressure, retention cleanup, snapshot/gap behavior, and one-worker enforcement.
- Add SSE-failure polling reconciliation and ambiguous-POST behavior.
- Test browser disconnect before it receives a run ID, normal reconnect, subscriber loss, process metadata reload, unauthorized session/history access, unauthorized resume/approve/stop, stopping-to-cancelled, no duplicate POST, explicit owner release from `acceptance_unknown`, owner-target uncertainty fencing, and two-turn context continuity.
- Simulate a server that accepts the Runs request and drops its response; prove the turn remains locked with no automatic retry and that neither session history nor reconnect silently releases it.
- Test resolved Hermes session-ID rotation after compression and an ownership-conflict failure.
- Test approval labels/scopes, `allow_permanent: false`, deployment-policy disablement, and second confirmation before any persistent allowlist mutation.

**Gate:** deterministic backend protocol tests prove one Hermes POST across disconnect/reconnect, a locked and owner-acknowledged ambiguous submission, correct resolved-session adoption, approval-scope safety, and a second turn receiving the first turn's dialogue context without the console persisting content.

### Phase 4 — Add text fallback, the dual experience, and a safe live smoke command

**Files:** shared input validator, socket protocol, console controller/shells/shared UI primitives, app state/tests, `backend/voice_console/smoke.py`, CLI and smoke tests.

- Add configurable `max_input_text_chars`.
- Route typed text and STT output through the same validator and `RunCoordinator.start` path.
- Disable mic and text input while the session lock is active.
- Clear typed input only after accepted-run confirmation.
- Implement the desktop command bar, conversation rail/workspace, and live inspector over real shared state.
- Implement the simplified mobile header, conversation surface, sticky composer, activity sheet, settings sheet, and full-screen approval presentation over the same controller.
- Replace raw approval JSON as the primary explanation with normalized context, exact run/persistent scope, event-policy filtering, and consequence copy.
- Use “JobHunter/agent response” and configured-model terminology rather than calling Hermes the model.
- Add `voice-console smoke --target job-hunter --read-only`.
- Read-only smoke calls public `/health`, authenticated `/health/detailed`, `/v1/capabilities`, `/v1/toolsets`, and `/v1/models`. Models verifies API/profile aliases and routes, not the effective inference model.
- Treat `/health/detailed` HTTP 200 as transport success only; inspect its top-level and readiness status.
- Write smoke requires both `--allow-run` and explicit text. It prints status/event names and timing, not prompt/response content or credentials.
- Approval and stop exercises are separate opt-in flags and use harmless prompts.

**Gate:** local fake text flow, both presentation shells, shell-switch single-controller tests, accessible approval tests, and sanitized smoke tests pass before touching JobHunter configuration.

### Phase 5 — Package a portable container before the first droplet deployment

**Files:** `Dockerfile`, `.dockerignore`, `deploy/compose.example.yaml`, `deploy/compose.jobhunter.example.yaml`, container smoke config, Makefile and deployment docs.

- Multi-stage Node frontend build plus slim Python runtime.
- Runtime Clerk public config means no deployment-specific key is baked into the image.
- Run non-root in the container and use Python—not curl—for the healthcheck.
- Package frontend assets where the installed Python service can find them; verify both source checkout and wheel/container paths.
- Add real optional dependency groups for advertised Edge TTS and faster-whisper providers, or stop claiming a base install provides them.
- Provide an exact fake-target/container smoke compose stack; do not rely on absent `config/voice.yaml`, `config/targets.yaml`, or `.env` files.
- The JobHunter Linux compose example uses `network_mode: host`, one application worker, console bind `127.0.0.1:8788`, absolute config paths, and restart policy. Host networking is required so a container can reach Hermes' loopback-only 8642.
- Run Uvicorn with proxy headers enabled but `forwarded-allow-ips=127.0.0.1`, so only the loopback Tailscale Serve hop may define the external scheme/host.

**Gate:** fresh image build, healthcheck, fake protocol turn, frontend load, and clean shutdown pass locally.

### Phase 6 — Enable and prove the JobHunter API Server without source/workspace edits

**Permitted remote mutation after plan approval:** `/root/.hermes/profiles/job-hunter/.env` plus service restart. Do not edit `/root/.hermes/hermes-agent` or `/root/DEV/job-hunter`.

1. Re-capture source/workspace status, service state, env variable-name counts, ports, and Tailscale config.
2. If the Hermes commit differs from the audited `7b5ba205`, re-audit the Runs, sessions, capability, toolset, approval, stop, and delegation paths before enabling anything.
3. Take a permission-preserving, timestamped profile-env backup.
4. Stop on duplicate API Server variables.
5. Deliberately upsert exact non-secret values:

   ```text
   API_SERVER_ENABLED=true
   API_SERVER_HOST=127.0.0.1
   API_SERVER_PORT=8642
   ```

6. Preserve an existing strong `API_SERVER_KEY`; otherwise generate 32 random bytes. Never print it.
7. Copy only that key into the console environment as `JOB_HUNTER_API_SERVER_KEY`; do not copy the whole Hermes profile env.
8. Verify one occurrence of every variable without printing values and retain an exact rollback procedure.
9. Restart only `hermes-gateway-job-hunter.service` and inspect scoped warnings/errors.
10. Confirm only `127.0.0.1:8642` is listening.
11. Open a temporary SSH local forward over Tailscale from `127.0.0.1:<unused>` on the development Mac to `127.0.0.1:8642` on `job-hunter`. Point all local preflight and console checks at that loopback tunnel; never expose the raw Hermes API to the LAN or tailnet.
12. Run the read-only smoke through the tunnel and stop if any required capability/runtime/toolset assumption fails.
13. Confirm source/workspace parity, configured `openai-codex`/`gpt-5.5`, and Codex OAuth again. Treat profile config as configured-primary evidence, not proof that fallback cannot occur during a future run.
14. Start the local console in service mode with a temporary JobHunter target configuration. Run all write/continuity checks through the console's real `SessionManager`, `RunCoordinator`, ownership mapping, and service-auth protocol. Direct Hermes calls are preflight only.
15. Run one harmless text request. Do not auto-retry an ambiguous submission.
16. Run the nonce-recall, prior-tool-result follow-up, New Conversation rotation, resolved-ID compression continuity, and long-context tests.
17. Exercise deny/approval and cooperative stop only with harmless, workspace-free prompts. Keep persistent approval disabled. If a safe prompt does not trigger approval, record “not exercised” instead of escalating risk.
18. Exercise a harmless delegation and report only tool start/completion proven by events. Confirm that a `background=true` request remains synchronous on the API surface; do not claim detached work or nested progress.
19. Stop the temporary console and SSH forward and verify no test listener remains.

**Gate:** real single-turn and multi-turn dialogue complete through JobHunter with correct harness/profile/provider configuration evidence, API-specific tool evidence, and no Hermes source or JobHunter workspace changes attributable to setup.

### Phase 7 — Deploy the first visible console on a non-conflicting tailnet endpoint

- Transfer a pinned source commit/archive to `/opt/hermes-voice-console`; do not deploy inside the Hermes checkout or JobHunter workspace.
- Build and run the reference container with Docker Compose and host networking.
- Use Clerk development credentials for this tailnet-only proof.
- Configure Clerk and the console with the exact resolved `https://<tailnet-fqdn>:9443` origin. Keep the private FQDN in deployment configuration/evidence, not hard-coded in the portable repository.
- Recheck 8788 and 9443 immediately before use.
- Save both `tailscale serve status --json` and `tailscale serve get-config --all` before the change.
- Add only this new endpoint:

  ```bash
  tailscale serve --bg --https=9443 http://127.0.0.1:8788
  ```

- Never use `tailscale serve reset`.
- Canonicalize the before/after Serve JSON and verify that the only semantic change is the new 9443 handler.
- Roll back only this endpoint with `tailscale serve --https=9443 off`.
- Confirm neither Hermes 8642 nor the console's raw loopback port is directly exposed.

**First desktop usability gate:** on the laptop, the owner uses the command center to select JobHunter, create/select a conversation, send follow-up text turns, watch streaming output and tool activity in the inspector, understand harness/run state, and use approval/stop controls. Stop for hands-on review of the desktop interaction model before deeper voice polish.

### Phase 8 — Upgrade and verify the actual turn-based voice loop

**Files:** provider/config modules and tests, capture/playback protocol, sentence buffer/TTS session, UI controls and copy.

- Upgrade the default STT model and provider naming.
- Add STT hallucination/empty-audio filtering.
- Propagate TTS MIME type and `(turn_id, chunk_index)` through playback.
- Add sequential sentence-level synthesis, markdown/think stripping, caps, timeouts, cancel, stale-chunk rejection, and no audio replay on recovery.
- Add a measured input-level visualization, elapsed/max recording time, two-tap recording controls, native keyboard operation, and audio-playback unlock/fallback.
- Make the mobile composer safe-area aware with dynamic viewport units; verify the virtual keyboard does not cover text or critical controls.
- Add `visibilitychange`/`pageshow` recovery, forced-colors styles, visible focus, reduced-motion variants, and throttled semantic state announcements.
- Ensure no critical desktop action or explanation is hover-only.
- Add the visible AI-voice disclosure.
- Keep a TTS failure non-fatal: text remains complete and usable.

**Gate:** real OpenAI transcription and selected TTS pass in both shells; conversation history reloads; cancel speech does not stop the agent run; stopping the run does not erase text; and backgrounded or explicitly discarded recordings do not submit audio.

### Phase 9 — Phone, reconnection, and browser-level proof

- Add a real browser acceptance suite that loads built React against the fake backend in loopback development mode. Keep the existing FastAPI test but rename its claim to backend protocol integration.
- Test 1440×900 and 1280×800 desktop command-center layouts with the persistent inspector.
- Test 1024×768 compact desktop with the inspector drawer.
- Test 390×844 phone portrait and 844×390 coarse-pointer phone landscape with the simplified shell.
- Verify secure-context microphone behavior, permission denial, tap-to-record, typed fallback, persistent conversation history, response, tool timeline, approval, stop, cancel speech, and AI disclosure.
- Test desktop keyboard-only operation, visible focus, reduced motion, forced colors, and screen-reader state announcements.
- Test mobile virtual-keyboard/safe-area behavior, rotation, and backgrounding during an unsubmitted recording.
- Sleep/close the phone during an accepted harmless run and verify recovery without duplicate run creation.
- Test browser disconnect before `agent.run.started`, console-to-Hermes SSE failure, and console-process restart reconciliation.
- Test approvals in desktop and mobile presentations with long details, least-destructive focus, containment, Escape policy, and logical focus return.
- Assert one mounted shell, one controller, one socket, and one run submission across layout changes.
- Confirm browser storage contains only the expiring non-secret recovery schema.

**V1 acceptance gate:** the laptop delivers the rich command-center workflow and the phone delivers the simplified companion workflow. From either, an allowed user can speak or type to JobHunter, continue a real conversation, watch appropriately presented work, hear the answer, approve or deny, stop explicitly, cancel only speech, and reconnect without duplicate or accidental cancellation.

### Phase 10 — Public release and upstream posture

- Owner chooses MIT or Apache-2.0 before `LICENSE` is added.
- Add contribution, security, privacy, architecture, configuration, container, systemd/venv, generic proxy, rollback, and release docs.
- Add CI for backend, Ruff, frontend, browser acceptance, fake protocol integration, container build, and secret scanning.
- Build a wheel from the release candidate, install it into a brand-new temporary Python 3.11 virtual environment with no editable checkout, start the packaged fake target/console, load packaged frontend assets, complete a fake protocol turn, and remove the environment.
- Pin GitHub Actions to full commit SHAs with version comments.
- Audit current working tree and full Git history for secrets before making the repository public.
- Publish a versioned standalone release and container image from the same tested commit.
- Sanitize JobHunter evidence: hashes, gate results, event names, device/browser classes, and timing only.

Current upstream overlap must be reviewed again at release time:

- Hermes issue #20765;
- Hermes issue #54352;
- draft Hermes PR #20871, which targets dashboard/browser voice over Tailscale;
- existing dashboard-only `/api/audio/transcribe` and `/api/audio/speak` routes.

The standalone project remains distinct because it provides Clerk auth, API-Server portability, a rich desktop command center plus simplified mobile companion, backend-owned durable runs, approvals, and no dashboard/PTY dependency. Do not promise or automatically open an upstream PR. Search open and merged work first, publish the standalone proof, then ask maintainers whether a documentation listing or a focused generic API improvement is wanted. The strongest currently identified generic gap is allowing Runs to load existing SessionDB dialogue when `session_id` is provided, matching the continuity behavior exposed elsewhere. Hermes' programmatic-integration guidance explicitly positions the API Server for custom web frontends, which supports keeping this product outside the core source tree.

## Research Anchors

- [Hermes API Server guide at the audited commit](https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/website/docs/user-guide/features/api-server.md)
- [Hermes API Server implementation at the audited commit](https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/gateway/platforms/api_server.py)
- [Hermes provider/runtime architecture](https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/website/docs/developer-guide/provider-runtime.md)
- [Hermes programmatic integration surfaces](https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/website/docs/developer-guide/programmatic-integration.md)
- [Hermes delegation implementation](https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/tools/delegate_tool.py)
- [Hermes platform toolsets](https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/toolsets.py)
- [Current overlapping browser-voice issue](https://github.com/NousResearch/hermes-agent/issues/54352) and [draft dashboard PR](https://github.com/NousResearch/hermes-agent/pull/20871)
- [Clerk Core 3 React control surface](https://clerk.com/docs/react/reference/components/control/show), [session tokens](https://clerk.com/docs/guides/sessions/session-tokens), and [production-domain requirements](https://clerk.com/docs/guides/development/deployment/production)
- [OpenAI speech-to-text](https://developers.openai.com/api/docs/guides/speech-to-text) and [text-to-speech](https://developers.openai.com/api/docs/guides/text-to-speech)
- [Tailscale Serve command contract](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [Pointer Events capture](https://developer.mozilla.org/en-US/docs/Web/API/Element/setPointerCapture), and [page restoration behavior](https://developer.mozilla.org/en-US/docs/Web/API/Window/pageshow_event)

## Verification Matrix

| Gate | Required proof |
|---|---|
| Baseline | pytest, Ruff, frontend lint/typecheck/unit/build all green |
| Auth | Clerk 401/403, service token, WS origin/expiry/refresh, no token storage |
| Fake transport | one run POST, events, approval scopes, stop, disconnect/reconnect, ambiguous acceptance lock, no duplicate |
| Session continuity | owned-session isolation, nonce recall, prior-result follow-up, New Conversation, resolved-ID compression, long-context behavior |
| Browser fake | built React loads exactly one shell/controller and completes text plus fake voice turn |
| JobHunter read-only | liveness, readiness, session/run capabilities, API aliases, toolsets, harness/runtime identity |
| JobHunter write | harmless multi-turn dialogue, event names, synchronous delegation, cooperative stop, safe approval attempt |
| Desktop | Clerk dev sign-in, session rail, text/PTT, conversation, inspector, approvals, TTS, keyboard/accessibility |
| Mobile | simplified shell, HTTPS mic, sticky composer, sheets, rotation/background/reconnect, no duplicate run |
| Portability | fresh container plus actual clean-wheel/fresh-venv install and fake turn |
| Public release | CI, secret/history audit, license, docs, tagged image/release |

## Hard Stop Conditions

Stop and ask the owner before implementation continues if:

- live Hermes lacks a required capability or runtime identity;
- enabling the adapter would require a Hermes source edit;
- Hermes source or JobHunter workspace changes unexpectedly;
- 8788 or 9443 becomes occupied;
- adding Tailscale Serve would replace an existing route;
- Clerk development credentials or exact authorized origins are unavailable;
- the OpenAI speech model selected for deployment is unavailable;
- a live write test would require a risky tool action;
- owned-session isolation or any required multi-turn continuity test fails;
- an ambiguous run POST cannot be reconciled safely;
- the owner cannot explicitly resolve an `acceptance_unknown` lock without an automatic or misleading retry;
- public release reaches the unresolved license choice.

## Definition of Done

- Implementation uses normal tools and agent delegation; no skill is invoked to execute the plan.
- Human auth uses Clerk; programmatic auth uses an optional service credential; neither enters URLs or storage.
- Hermes stays on loopback and requires its own strong API key.
- The console uses the supported API Server without importing or modifying the Hermes harness.
- JobHunter retains its current profile, configured `openai-codex`/`gpt-5.5` primary inference path, workspace, memory backing, and API-specific resolved toolset.
- The UI distinguishes harness, agent/profile, provider, configured model, run, and response accurately.
- Owned conversation IDs, Hermes transcript sessions, explicit dialogue history, and long-term-memory scope are handled separately and correctly.
- Hermes compression/resume session-ID rotation is adopted atomically without changing the user-visible conversation or ownership.
- Accepted runs survive browser disconnect; broken SSE is reconciled by status polling without re-post.
- Ambiguous submissions remain content-free, locked, non-retried, and owner-acknowledged before release.
- Approval, stop, and speech cancellation remain separate and owner-authorized.
- Approval copy reflects actual scope: `session` lasts only for the current Run, and persistent `always` is disabled by default and never offered against `allow_permanent: false`.
- The unrelated service on 8787 and every existing Tailscale route remain untouched.
- Laptop passes the rich desktop command-center journey; phone passes the simplified companion journey over the same controller.
- Detached background delivery is documented as future transport work; current API delegation is accurately described as synchronous fallback.
- The standalone project is tested and released before any upstream integration proposal.
