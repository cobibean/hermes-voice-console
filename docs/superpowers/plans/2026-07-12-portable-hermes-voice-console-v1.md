# Portable Hermes Voice Console V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Clerk-authenticated, turn-based browser voice console that can talk to the real JobHunter Hermes profile from a laptop and phone, survive browser reconnects without duplicating accepted runs, and remain portable enough to publish as a standalone open-source project.

**Architecture:** Keep the existing React/Vite browser and FastAPI service as a standalone adapter around Hermes' supported HTTP/SSE API. Replace static human tokens with Clerk session JWTs, preserve a separate opt-in service credential for tests, move accepted Hermes runs into a backend-owned run manager, and expose only the console through HTTPS while Hermes stays on loopback.

**Tech Stack:** Python 3.11+, FastAPI, httpx, PyJWT 2.13.0 with cryptography, React 19, TypeScript, Vite, `@clerk/react` 6.12.2, Vitest, pytest, systemd, Docker, and Tailscale Serve.

## Global Constraints

- The approved design in `docs/plans/2026-07-12-portable-hermes-voice-console-design.md` is the product source of truth.
- Do not import Hermes internals or edit `/root/.hermes/hermes-agent` to make the console work.
- Do not touch the dirty JobHunter workspace at `/root/DEV/job-hunter` during deployment.
- The Hermes API Server stays on `127.0.0.1:8642`; only the console is reachable through the HTTPS boundary.
- A Clerk user ID must be present in the deployment allowlist before that user can reach targets.
- A service credential is optional, server-side, absent from the human UI, and never transmitted in a URL.
- Closing a browser must not call Hermes stop. Only the explicit stop action may stop a run.
- Keep transcripts, response content, Clerk tokens, provider credentials, and Hermes keys out of logs.
- Do not add Realtime speech-to-speech, Discord session bridging, organizations, concurrent turns, or native mobile scope.
- Use test-first steps and commit after each task passes its stated verification.

---

## Phase 1: Replace the Static Auth Seam

### Task 1: Add the production authentication configuration model

**Files:**

- Modify: `pyproject.toml`
- Modify: `backend/voice_console/config.py`
- Modify: `config/voice.example.yaml`
- Modify: `config/voice.fake.yaml`
- Modify: `.env.example`
- Modify: `tests/backend/test_config_auth.py`

- [ ] **Step 1: Write failing configuration tests**

Add tests covering Clerk mode, service-token mode, the allowed-user list, authorized parties, and loopback-only development mode:

```python
def test_clerk_auth_config_requires_issuer_and_allowed_users(tmp_path):
    voice = tmp_path / "voice.yaml"
    write_yaml(voice, {
        "server": {"host": "127.0.0.1"},
        "auth": {
            "mode": "clerk",
            "clerk_issuer": "https://example.clerk.accounts.dev",
            "allowed_user_ids": ["user_jobhunter_owner"],
            "authorized_parties": ["https://voice.example.test"],
            "service_token_env": "VOICE_CONSOLE_SERVICE_TOKEN",
            "service_name": "smoke-test",
        },
        "voice": {"stt_provider": "fake", "tts_provider": "fake"},
    })
    config = load_console_config(voice)
    assert config.auth.mode == "clerk"
    assert config.auth.allowed_user_ids == ("user_jobhunter_owner",)
    assert config.auth.jwks_url == "https://example.clerk.accounts.dev/.well-known/jwks.json"


def test_development_auth_rejects_non_loopback_bind(tmp_path):
    voice = tmp_path / "voice.yaml"
    write_yaml(voice, {
        "server": {"host": "0.0.0.0"},
        "auth": {"mode": "development"},
        "voice": {"stt_provider": "fake", "tts_provider": "fake"},
    })
    with pytest.raises(ConfigError, match="loopback"):
        load_console_config(voice)
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `. .venv/bin/activate && pytest tests/backend/test_config_auth.py -q`

Expected: failures because `ConsoleConfig` does not yet expose `auth`.

- [ ] **Step 3: Add exact runtime dependencies**

Add `"PyJWT[crypto]==2.13.0"` to `[project].dependencies`. Do not add a second web framework or a Clerk backend SDK; JWT/JWKS verification is the only backend capability required.

- [ ] **Step 4: Implement the auth configuration dataclass**

Add this shape to `backend/voice_console/config.py` and include it in `ConsoleConfig`:

```python
@dataclass(frozen=True)
class AuthConfig:
    mode: str = "clerk"
    clerk_issuer: str = ""
    allowed_user_ids: tuple[str, ...] = ()
    authorized_parties: tuple[str, ...] = ()
    service_token_env: str = ""
    service_name: str = "automation"
    websocket_auth_timeout_seconds: int = 5
    websocket_refresh_grace_seconds: int = 90

    @property
    def jwks_url(self) -> str:
        return f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json"
```

Parse a top-level `auth:` mapping. Accept only `clerk`, `service`, or `development`. Resolve `clerk_issuer` from the mapping first and then `CLERK_ISSUER`; resolve comma-separated allowed user IDs and authorized parties from their mappings first and then `VOICE_CONSOLE_ALLOWED_USER_IDS` and `VOICE_CONSOLE_AUTHORIZED_PARTIES`. Clerk mode must have a HTTPS issuer and at least one allowed user. Service mode must name a usable token environment variable. Development mode must reject any server host other than `127.0.0.1`, `::1`, or `localhost`.

- [ ] **Step 5: Update example configuration without real credentials**

Replace `server.auth_required` in `config/voice.example.yaml` with an `auth` section. Convert `config/voice.fake.yaml` to `auth.mode: service` so local testing remains usable. Add only variable names to `.env.example`: `VITE_CLERK_PUBLISHABLE_KEY`, `CLERK_ISSUER`, `VOICE_CONSOLE_ALLOWED_USER_IDS`, `VOICE_CONSOLE_AUTHORIZED_PARTIES`, `VOICE_CONSOLE_SERVICE_TOKEN`, and the target/provider variables. Also correct `FAKE_HERMES_API_KEY` to `fake` so the example matches `backend/voice_console/fake_target.py`.

- [ ] **Step 6: Run tests and commit**

Run: `. .venv/bin/activate && pytest tests/backend/test_config_auth.py -q && ruff check backend/voice_console/config.py tests/backend/test_config_auth.py`

Expected: all focused tests pass and Ruff reports no errors.

Commit: `git add pyproject.toml backend/voice_console/config.py config/voice.example.yaml config/voice.fake.yaml .env.example tests/backend/test_config_auth.py && git commit -m "Add portable auth configuration"`

### Task 2: Implement Clerk, service, and development principals

**Files:**

- Replace: `backend/voice_console/auth.py`
- Create: `tests/backend/test_auth.py`

- [ ] **Step 1: Write failing authenticator tests**

Cover valid Clerk JWT, expired JWT, wrong issuer, wrong `azp`, disallowed `sub`, valid service token, wrong service token, and development principal. Mock the JWKS lookup; unit tests must not call Clerk over the network.

Use this principal contract:

```python
@dataclass(frozen=True)
class Principal:
    kind: Literal["clerk", "service", "development"]
    subject: str

    @property
    def audit_id(self) -> str:
        return f"{self.kind}:{self.subject}"
```

- [ ] **Step 2: Confirm the new tests fail**

Run: `. .venv/bin/activate && pytest tests/backend/test_auth.py -q`

Expected: import failures for `Principal` and `Authenticator`.

- [ ] **Step 3: Implement one asynchronous authentication boundary**

Replace `AuthGate` with an `Authenticator` that exposes:

```python
class AuthenticationError(ValueError):
    pass


class Authenticator:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self._jwk_client = jwt.PyJWKClient(config.jwks_url) if config.mode == "clerk" else None

    async def authenticate(self, token: str | None) -> Principal:
        if self.config.mode == "development":
            return Principal(kind="development", subject="loopback")
        if self._matches_service_token(token):
            return Principal(kind="service", subject=self.config.service_name)
        return await self._authenticate_clerk(token)
```

Run `PyJWKClient.get_signing_key_from_jwt` with `asyncio.to_thread`. Decode with algorithm `RS256`, the configured issuer, required `exp`, `iat`, and `sub` claims, and five seconds of leeway. Validate `azp` against `authorized_parties` when that list is non-empty. Reject a valid JWT whose `sub` is not in `allowed_user_ids`. Use `hmac.compare_digest` for the optional service token.

- [ ] **Step 4: Keep startup diagnostics safe**

Expose warnings for missing service-token values and development mode, but never include a token, JWT claim set, or Clerk key in warning text.

- [ ] **Step 5: Run tests and commit**

Run: `. .venv/bin/activate && pytest tests/backend/test_auth.py -q && ruff check backend/voice_console/auth.py tests/backend/test_auth.py`

Expected: all authenticator tests pass.

Commit: `git add backend/voice_console/auth.py tests/backend/test_auth.py && git commit -m "Verify Clerk and service principals"`

### Task 3: Authenticate HTTP and WebSocket traffic without URL credentials

**Files:**

- Modify: `backend/voice_console/app.py`
- Modify: `backend/voice_console/protocol.py`
- Modify: `tests/backend/test_config_auth.py`
- Modify: `tests/backend/test_protocol_session_audio.py`
- Modify: `backend/voice_console/fake_e2e.py`

- [ ] **Step 1: Add failing HTTP and WebSocket tests**

The tests must prove:

- `/api/bootstrap` returns `401` without a bearer credential.
- A service bearer returns `200` and bootstrap includes `principal.kind == "service"` without exposing the subject.
- `/ws/voice?token=anything` does not authenticate.
- The first WS text frame must be `{ "type": "auth", "token": "test-service-token-000000" }`.
- The server sends `authenticated` before it accepts `hello`.
- Missing auth times out and closes with code `4401`.
- An invalid `auth.refresh` closes with `4401`.

- [ ] **Step 2: Confirm failures**

Run: `. .venv/bin/activate && pytest tests/backend/test_config_auth.py tests/backend/test_protocol_session_audio.py -q`

Expected: current query-token behavior violates the new assertions.

- [ ] **Step 3: Wire asynchronous HTTP bearer verification**

Add an async dependency inside `create_app` that reads only `Authorization: Bearer`. Return a `Principal`; do not accept query parameters or `X-Voice-Console-Token`. Include only `{ "kind": principal.kind }` in `/api/bootstrap`.

- [ ] **Step 4: Implement the WS authentication state machine**

Call `ws.accept()` before reading the encrypted auth frame, then apply `asyncio.wait_for` using `websocket_auth_timeout_seconds`. The valid order is:

```text
client auth -> server authenticated -> client hello -> server ready
```

After `ready`, accept `auth.refresh` at any time and update the connection's authentication deadline. Never put token, target, session, or run identifiers into the WebSocket URL. Close `4401` for authentication errors and `4403` for allowlist denial.

- [ ] **Step 5: Convert fake E2E to the service credential**

Set `auth.mode: service`, set `VOICE_CONSOLE_SERVICE_TOKEN`, connect to `/ws/voice` without query parameters, send the auth frame, assert `authenticated`, and then continue the existing deterministic turn.

- [ ] **Step 6: Run backend verification and commit**

Run: `. .venv/bin/activate && pytest tests/backend -q && voice-console fake-e2e && ruff check backend tests/backend`

Expected: backend suite passes, fake E2E reports `"ok": true`, and no URL contains a credential.

Commit: `git add backend/voice_console/app.py backend/voice_console/protocol.py backend/voice_console/fake_e2e.py tests/backend && git commit -m "Authenticate console protocol frames"`

---

## Phase 2: Put Clerk in the Human Journey

### Task 4: Add Clerk to the React entrypoint and API client

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/api.test.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/vite-env.d.ts`

- [ ] **Step 1: Install the current Clerk React package**

Run: `cd frontend && pnpm add @clerk/react@6.12.2`

Expected: package and lockfile resolve `@clerk/react` 6.12.2.

- [ ] **Step 2: Write failing API token-provider tests**

Replace the string token API with this interface:

```typescript
export type TokenProvider = () => Promise<string | null>;

export async function apiFetch<T>(path: string, getToken: TokenProvider, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json() as Promise<T>;
}
```

Tests must assert that token retrieval occurs per request, no token is written to `localStorage` or `sessionStorage`, and `401` produces an auth-specific error.

- [ ] **Step 3: Confirm tests fail, then implement**

Run: `cd frontend && pnpm test -- src/lib/api.test.ts`

Expected before implementation: failures for `TokenProvider` and storage assertions. Expected after implementation: all tests pass.

- [ ] **Step 4: Mount ClerkProvider**

Read `VITE_CLERK_PUBLISHABLE_KEY` once in `main.tsx`. Throw a visible startup error when it is absent in a production build. Wrap `<App />` in `<ClerkProvider publishableKey={publishableKey}>`.

- [ ] **Step 5: Run frontend checks and commit**

Run: `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

Expected: all commands pass.

Commit: `git add frontend && git commit -m "Add Clerk session token plumbing"`

### Task 5: Replace the token form with Clerk sign-in and account controls

**Files:**

- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/components/components.test.tsx`
- Create: `frontend/src/test/clerk.tsx`

- [ ] **Step 1: Write failing signed-out, loading, allowed, and denied UI tests**

Use Clerk test doubles that model `isLoaded`, `isSignedIn`, `getToken`, and `signOut`. Assert:

- signed-out users see Clerk's `SignIn` component;
- session loading does not briefly show the console;
- signed-in users call bootstrap with `getToken`;
- backend `403` renders “This Clerk account is not allowed for this console”;
- no “Console token” input or unlock button exists.

- [ ] **Step 2: Confirm tests fail**

Run: `cd frontend && pnpm test -- src/components/components.test.tsx`

Expected: current static token screen fails the new assertions.

- [ ] **Step 3: Implement the Clerk journey**

Use `SignedIn`, `SignedOut`, `SignIn`, `UserButton`, and `useAuth` from `@clerk/react`. Pass `getToken` to both HTTP and WebSocket clients. Keep sign-out distinct from disconnect; sign-out closes the socket but does not stop an accepted Hermes run.

- [ ] **Step 4: Preserve the existing console, then tighten mobile states**

Keep target/session selection, push-to-talk, transcript, response, diagnostics, timeline, approvals, stop, and cancel speech. Ensure the signed-out layout, microphone control, approval modal, and stop button work at 390 CSS pixels without horizontal scrolling.

- [ ] **Step 5: Run checks and commit**

Run: `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

Expected: all frontend gates pass and built JavaScript contains neither `VOICE_CONSOLE_SESSION_SECRET` nor `hvc.consoleToken`.

Commit: `git add frontend/src && git commit -m "Replace static login with Clerk"`

### Task 6: Refresh WebSocket authentication on live connections

**Files:**

- Modify: `frontend/src/lib/voiceClient.ts`
- Modify: `frontend/src/lib/voiceClient.test.ts`
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Write failing protocol-order and refresh tests**

Change `VoiceClientOptions.token` to `getToken: TokenProvider`. Assert the exact initial order is `auth`, wait for `authenticated`, `hello`, wait for `ready`. Assert the URL is exactly `/ws/voice` with no query string. Use fake timers to prove a new token is sent in `auth.refresh` every 30 seconds and timers stop on close.

- [ ] **Step 2: Confirm tests fail**

Run: `cd frontend && pnpm test -- src/lib/voiceClient.test.ts`

Expected: current client sends `hello` first and puts the token in the URL.

- [ ] **Step 3: Implement the token provider and refresh timer**

The connection must reject if `getToken()` returns null. It must not cache a Clerk token beyond the next refresh. Add these event types:

```typescript
type AuthenticatedEvent = {
  type: 'authenticated';
  principal: { kind: 'clerk' | 'service' | 'development' };
};

type AuthExpiringEvent = {
  type: 'auth.expiring';
  refresh_within_seconds: number;
};
```

- [ ] **Step 4: Run checks and commit**

Run: `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

Expected: all checks pass; the WebSocket test proves the URL has no credential.

Commit: `git add frontend/src/lib && git commit -m "Refresh Clerk auth on voice sockets"`

---

## Phase 3: Make Turns Durable and Testable

### Task 7: Add text fallback through the same Hermes turn pipeline

**Files:**

- Modify: `backend/voice_console/app.py`
- Modify: `backend/voice_console/protocol.py`
- Modify: `frontend/src/lib/voiceClient.ts`
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/components/TextTurnForm.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/components.test.tsx`
- Modify: `tests/backend/test_protocol_session_audio.py`

- [ ] **Step 1: Add failing backend and frontend tests**

Define a `turn.submit` frame with `turn_id` and non-empty `text`. Test 16,000-character input rejection, control-character rejection, submission while busy, and successful routing through the same run code used after STT. Test that the UI disables text and microphone submission while a run is active.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `. .venv/bin/activate && pytest tests/backend/test_protocol_session_audio.py -q`

Run: `cd frontend && pnpm test -- src/components/components.test.tsx`

Expected: `turn.submit` is currently unknown and no text form exists.

- [ ] **Step 3: Extract a shared `submit_turn` backend function**

Both STT completion and text submission must call one function that enforces the single-active-run rule, emits `transcript.final` with provider `text` for typed input, and starts Hermes exactly once.

- [ ] **Step 4: Implement the mobile text form**

Add a compact textarea and Send button below voice controls. Preserve entered text after a transport failure; clear it only after `agent.run.started` confirms acceptance.

- [ ] **Step 5: Verify and commit**

Run: `. .venv/bin/activate && pytest tests/backend -q && cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

Expected: backend and frontend suites pass.

Commit: `git add backend/voice_console frontend/src tests/backend && git commit -m "Add text fallback for Hermes turns"`

### Task 8: Move accepted Hermes runs out of the browser socket lifecycle

**Files:**

- Create: `backend/voice_console/run_manager.py`
- Modify: `backend/voice_console/app.py`
- Modify: `backend/voice_console/hermes_client.py`
- Modify: `backend/voice_console/fake_target.py`
- Create: `tests/backend/test_run_manager.py`
- Modify: `tests/backend/test_fake_e2e.py`

- [ ] **Step 1: Write failing run-manager tests**

Test these invariants with the fake target:

- `POST /v1/runs` returning a run ID makes that run backend-owned;
- disconnecting the only subscriber does not cancel the SSE consumer or call stop;
- reconnecting the same principal and session receives buffered events and then live events;
- a second submission for the same target/session returns `agent_busy`;
- a different principal cannot attach to the run;
- explicit stop calls Hermes stop exactly once;
- terminal runs release the session lock;
- event buffers cap at 250 normalized events.

- [ ] **Step 2: Confirm tests fail**

Run: `. .venv/bin/activate && pytest tests/backend/test_run_manager.py -q`

Expected: `RunManager` does not exist.

- [ ] **Step 3: Implement the backend-owned run record**

Use this public shape:

```python
@dataclass
class RunRecord:
    run_id: str
    target_name: str
    session_id: str
    owner_audit_id: str
    status: Literal["running", "waiting_for_approval", "completed", "failed", "stopped"]
    events: deque[SequencedEvent]
    subscribers: set[asyncio.Queue[SequencedEvent]]
```

Implement `RunManager.start(request) -> RunRecord`, `RunManager.subscribe(run_id, principal, after_sequence) -> AsyncIterator[SequencedEvent]`, and `RunManager.stop(run_id, principal) -> dict[str, Any]` as complete concrete methods. Start the Hermes event consumer with `asyncio.create_task` owned by `RunManager`, not by the WebSocket handler. Cancel subscriber-forwarding tasks on disconnect, but leave the run consumer alive.

- [ ] **Step 4: Add reconnect protocol fields**

`hello` may include `resume_run_id` and `after_sequence`. Every run event includes `sequence`. A successful reattach emits `agent.run.resumed` before buffered events. A terminal buffered event prevents a duplicate run.

- [ ] **Step 5: Extend fake E2E with a disconnect/reconnect case**

Start a delayed fake run, close the first WebSocket after `agent.run.started`, reconnect and authenticate, resume by run ID, and assert one `run.completed` with one fake-target start count.

- [ ] **Step 6: Verify and commit**

Run: `. .venv/bin/activate && pytest tests/backend -q && voice-console fake-e2e && ruff check backend tests/backend`

Expected: disconnect/reconnect E2E completes without a second Hermes run.

Commit: `git add backend/voice_console tests/backend && git commit -m "Keep Hermes runs alive across reconnects"`

### Task 9: Restore active-run state in the browser

**Files:**

- Modify: `frontend/src/lib/voiceClient.ts`
- Modify: `frontend/src/lib/voiceClient.test.ts`
- Create: `frontend/src/lib/runRecovery.ts`
- Create: `frontend/src/lib/runRecovery.test.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/lib/state.ts`
- Modify: `frontend/src/lib/state.test.ts`

- [ ] **Step 1: Write failing recovery tests**

Store only `{ target, sessionId, runId, lastSequence }` under one versioned `localStorage` key. Test that no token, transcript, assistant content, approval payload, or provider key is stored. Test reload reattach, terminal cleanup, wrong-session cleanup, and duplicate-delta prevention by sequence.

- [ ] **Step 2: Confirm tests fail**

Run: `cd frontend && pnpm test -- src/lib/runRecovery.test.ts src/lib/state.test.ts src/lib/voiceClient.test.ts`

Expected: recovery module and `agent.run.resumed` handling do not exist.

- [ ] **Step 3: Implement recovery metadata and reconnect UI**

Write metadata only after `agent.run.started`; advance `lastSequence` after each run event; clear after terminal events. On page load, connect with `resumeRunId` before enabling a new turn. Show “Reconnecting to Hermes run” instead of returning to idle. Never call `turn.submit` during recovery.

- [ ] **Step 4: Verify and commit**

Run: `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

Expected: all checks pass and storage tests prove only non-secret identifiers persist.

Commit: `git add frontend/src && git commit -m "Recover active runs after browser reconnect"`

### Task 10: Queue completed sentences for TTS without coupling speech to the run

**Files:**

- Create: `backend/voice_console/sentence_buffer.py`
- Create: `tests/backend/test_sentence_buffer.py`
- Modify: `backend/voice_console/app.py`
- Modify: `frontend/src/lib/playback.ts`
- Modify: `frontend/src/lib/playback.test.ts`
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Write failing sentence-buffer tests**

Test punctuation boundaries, abbreviation safety for `Mr.` and `e.g.`, minimum chunk size, final flush, maximum text cap, and cancel behavior. Test that stopping playback does not call Hermes stop and stopping Hermes does not implicitly discard already visible text.

- [ ] **Step 2: Confirm tests fail**

Run: `. .venv/bin/activate && pytest tests/backend/test_sentence_buffer.py -q`

Run: `cd frontend && pnpm test -- src/lib/playback.test.ts`

Expected: no sentence buffer exists and playback assumes one terminal audio stream.

- [ ] **Step 3: Implement sequential TTS chunks**

Buffer live `agent.delta` text and synthesize completed sentences in order. Emit `tts.start`, binary chunks, and `tts.end` with both `turn_id` and a monotonically increasing `chunk_index`. Flush remaining text at `agent.completed`. One TTS worker per connection prevents overlapping playback. Replayed recovery events restore visible text but do not automatically replay audio, preventing a reconnect from speaking old sentences twice.

- [ ] **Step 4: Preserve failure isolation**

An STT error keeps text fallback usable. A TTS error emits a `tts_unavailable` layer error but leaves the full text response and Hermes run state intact. `tts.cancel` cancels current and queued speech for the turn only.

- [ ] **Step 5: Verify and commit**

Run: `. .venv/bin/activate && pytest tests/backend -q && cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build && cd .. && . .venv/bin/activate && voice-console fake-e2e`

Expected: all gates pass and fake E2E receives ordered audio chunks.

Commit: `git add backend/voice_console tests/backend frontend/src && git commit -m "Stream sentence-level voice playback"`

---

## Phase 4: Prove the Real JobHunter Path

### Task 11: Add a safe live-transport smoke command

**Files:**

- Create: `backend/voice_console/smoke.py`
- Modify: `backend/voice_console/cli.py`
- Create: `tests/backend/test_smoke.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI tests**

Test `voice-console smoke --target job-hunter --read-only` calls only health and capabilities. Test `--text "Reply with exactly: voice console transport ok"` requires `--allow-run`, prints event names but not event content, and exits nonzero on missing capabilities. Add `--exercise-stop` and `--exercise-approval` as separate explicit flags; neither runs by default.

- [ ] **Step 2: Confirm failure, then implement**

Run: `. .venv/bin/activate && pytest tests/backend/test_smoke.py -q`

Expected before implementation: the `smoke` command is absent. Expected after implementation: tests pass.

- [ ] **Step 3: Keep output sanitized**

Output target name, HTTP status, feature names, run ID, normalized event names, terminal status, and timing. Do not print prompts, responses, approval arguments, authorization headers, or environment values.

- [ ] **Step 4: Verify and commit**

Run: `. .venv/bin/activate && pytest tests/backend -q && ruff check backend tests/backend`

Expected: all checks pass.

Commit: `git add backend/voice_console tests/backend README.md && git commit -m "Add sanitized Hermes transport smoke tests"`

### Task 12: Enable the JobHunter API Server through profile configuration only

**Remote scope:**

- Read/modify: `/root/.hermes/profiles/job-hunter/.env`
- Restart: `hermes-gateway-job-hunter.service` in the root user systemd scope
- Read only: `/root/.hermes/hermes-agent`
- Do not touch: `/root/DEV/job-hunter`

- [ ] **Step 1: Capture the pre-change evidence without file contents**

Run remotely as root:

```bash
git -C /root/.hermes/hermes-agent status --short
git -C /root/.hermes/hermes-agent rev-parse HEAD
git -C /root/DEV/job-hunter status --short
systemctl --user is-active hermes-gateway-job-hunter.service
ss -ltn '( sport = :8642 )'
```

Expected: Hermes source is clean, JobHunter workspace may remain dirty, gateway is active, and port 8642 is not yet listening.

- [ ] **Step 2: Generate the API credential without printing it**

Run remotely:

```bash
umask 077
API_SERVER_KEY_VALUE="$(openssl rand -hex 32)"
grep -q '^API_SERVER_ENABLED=' /root/.hermes/profiles/job-hunter/.env || printf '%s\n' 'API_SERVER_ENABLED=true' >> /root/.hermes/profiles/job-hunter/.env
grep -q '^API_SERVER_HOST=' /root/.hermes/profiles/job-hunter/.env || printf '%s\n' 'API_SERVER_HOST=127.0.0.1' >> /root/.hermes/profiles/job-hunter/.env
grep -q '^API_SERVER_PORT=' /root/.hermes/profiles/job-hunter/.env || printf '%s\n' 'API_SERVER_PORT=8642' >> /root/.hermes/profiles/job-hunter/.env
grep -q '^API_SERVER_KEY=' /root/.hermes/profiles/job-hunter/.env || printf '%s\n' "API_SERVER_KEY=${API_SERVER_KEY_VALUE}" >> /root/.hermes/profiles/job-hunter/.env
unset API_SERVER_KEY_VALUE
chmod 600 /root/.hermes/profiles/job-hunter/.env
```

If any key already exists, stop and inspect only the variable name and duplicate count before changing it. Do not overwrite an existing value silently.

- [ ] **Step 3: Restart and inspect only scoped logs**

Run remotely:

```bash
systemctl --user restart hermes-gateway-job-hunter.service
systemctl --user is-active hermes-gateway-job-hunter.service
ss -ltn '( sport = :8642 )'
journalctl --user -u hermes-gateway-job-hunter.service --since '-2 minutes' --priority=warning --no-pager
```

Expected: service is active, `127.0.0.1:8642` is listening, and no warning or error indicates adapter startup failure.

- [ ] **Step 4: Run the read-only console smoke first**

Configure `config/targets.yaml` on the console host with target `job-hunter`, base URL `http://127.0.0.1:8642`, and key environment name `JOB_HUNTER_API_SERVER_KEY`. Load the value from the JobHunter profile env into the console service environment without printing it.

Run: `voice-console smoke --target job-hunter --read-only`

Expected: health succeeds and capabilities include runs, run events, approval, and stop.

- [ ] **Step 5: Confirm runtime identity before a write test**

Run remotely:

```bash
/root/.hermes/hermes-agent/venv/bin/hermes -p job-hunter auth status openai-codex
systemctl --user show hermes-gateway-job-hunter.service -p WorkingDirectory -p ExecStart
git -C /root/.hermes/hermes-agent status --short
git -C /root/DEV/job-hunter status --short
```

Expected: Codex OAuth is logged in, the service still uses profile `job-hunter`, Hermes source remains clean, and the pre-existing JobHunter workspace status is unchanged.

- [ ] **Step 6: Run one harmless accepted Hermes turn**

Run: `voice-console smoke --target job-hunter --text "Reply with exactly: voice console transport ok" --allow-run`

Expected: one run starts, event names stream, and the terminal state is completed. Review sanitized server logs for profile, model, and target identity without printing response content.

- [ ] **Step 7: Exercise approval and stop only with harmless prompts**

Use the smoke command's explicit flags with prompts designed to trigger a reversible, workspace-free action. Deny the approval on the first pass. Start a long harmless reasoning request and call stop. If Hermes does not request approval for the chosen harmless prompt, record that as “not exercised” rather than escalating to a risky tool.

- [ ] **Step 8: Capture post-change parity**

Re-run both git statuses and compare filenames and hashes to the pre-change evidence. The only intended remote file mutation is `/root/.hermes/profiles/job-hunter/.env`; no Hermes source or JobHunter workspace file may change as part of setup.

### Task 13: Deploy the console beside JobHunter and expose only it through Tailscale HTTPS

**Files:**

- Create: `deploy/systemd/hermes-voice-console.service`
- Create: `deploy/systemd/hermes-voice-console.env.example`
- Create: `docs/deploy-jobhunter.md`
- Modify: `docs/systemd-service.example.ini`
- Modify: `docs/rollback-uninstall.md`

- [ ] **Step 1: Write the generic service unit**

Use system-level systemd with `User=voice-console`, `Group=voice-console`, a configurable `/opt/hermes-voice-console` working directory, `EnvironmentFile=/etc/hermes-voice-console/env`, `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, and explicit writable state/temp directories. Bind the application to `127.0.0.1:8787`.

- [ ] **Step 2: Add install and rollback commands to the runbook**

The runbook must create a dedicated service user, clone a tagged release into `/opt`, build the frontend, create the venv, install the package, install config under `/etc/hermes-voice-console`, start the service, and show the inverse rollback commands. It must not assume a Hermes checkout path except in the separate JobHunter reference subsection.

- [ ] **Step 3: Configure Clerk deployment secrets**

Place the real Clerk publishable key in the frontend build environment. Place the Clerk issuer, allowed Clerk user ID, optional service token, Hermes target key, and STT/TTS keys in `/etc/hermes-voice-console/env` with mode `0600`. Do not copy the entire Hermes profile `.env` into the console.

- [ ] **Step 4: Start the console and run local probes**

Run remotely:

```bash
systemctl daemon-reload
systemctl enable --now hermes-voice-console.service
systemctl is-active hermes-voice-console.service
curl --fail --silent http://127.0.0.1:8787/health
```

Expected: the service is active and health reports `status: ok` with no credential values.

- [ ] **Step 5: Add a dedicated Tailscale Serve route without replacing existing routes**

First save `tailscale serve status --json` to the deployment evidence. Add a new HTTPS handler for `http://127.0.0.1:8787` using the host's current Tailscale CLI syntax. Re-read the JSON and prove the pre-existing routes on ports 80, 443, 8765, and 9100 are still represented. Do not expose 8642.

- [ ] **Step 6: Test laptop and phone**

On both devices, verify Clerk sign-in, allowlist rejection for a non-allowed account, target probe, text turn, push-to-talk, transcript, response text, TTS, cancel speech, explicit stop, and approval controls. On phone, sleep the browser during a harmless run, reopen it, and confirm `agent.run.resumed` without a second run ID.

- [ ] **Step 7: Commit deployment assets**

Run: `git diff --check && git add deploy docs README.md && git diff --cached --check && git commit -m "Document portable and JobHunter deployment"`

Expected: both diff checks pass and no remote credential or private hostname/IP is staged.

---

## Phase 5: Make the Repository Public-Release Ready

### Task 14: Add container packaging and CI

**Files:**

- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `deploy/compose.example.yaml`
- Create: `.github/workflows/ci.yml`
- Modify: `Makefile`
- Modify: `README.md`

- [ ] **Step 1: Add a multi-stage container**

Build frontend assets in a Node stage, install the Python wheel in a slim Python 3.12 runtime stage, run as a non-root user, expose 8787, and use `/health` for the healthcheck. No source checkout, build cache, `.env`, or provider credential may enter the final image.

- [ ] **Step 2: Add CI matching local gates**

On pull requests and pushes, run backend tests plus Ruff, frontend install/lint/typecheck/test/build, fake E2E, container build, `git diff --check`, and a secret scan. Pin action major versions and use the repository's lockfile.

- [ ] **Step 3: Verify the fresh container path**

Run:

```bash
docker build -t hermes-voice-console:test .
docker run --rm --name hvc-fake -p 127.0.0.1:8787:8787 --env-file .env -v "$PWD/config:/app/config:ro" hermes-voice-console:test
```

In a second terminal run `curl --fail http://127.0.0.1:8787/health`. Stop the container after the probe. Never use the JobHunter production env file for this test.

- [ ] **Step 4: Run the complete local gate and commit**

Run: `make test-all && . .venv/bin/activate && ruff check backend tests/backend && docker build -t hermes-voice-console:test .`

Expected: all tests, lint, builds, fake E2E, and container build pass.

Commit: `git add Dockerfile .dockerignore deploy/compose.example.yaml .github/workflows/ci.yml Makefile README.md && git commit -m "Add portable container and CI"`

### Task 15: Add public project governance, privacy proof, and release evidence

**Files:**

- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `docs/architecture.md`
- Create: `docs/privacy.md`
- Create: `docs/release-checklist.md`
- Create: `docs/evidence/jobhunter-smoke-template.md`
- Modify: `README.md`
- Modify: `docs/security.md`
- Modify: `docs/configuration.md`
- Modify: `docs/manual-smoke-checklist.md`

- [ ] **Step 1: Resolve the license as a human gate**

Before creating `LICENSE`, ask the repository owner to choose the license. Recommend Apache-2.0 for explicit patent terms or MIT for the shortest permissive grant. Do not infer the choice.

- [ ] **Step 2: Document the actual boundaries**

State clearly that Hermes is the agent, the console is a client, human access uses Clerk, provider/Hermes keys remain server-side, audio is deleted by default, content is not logged by default, and Realtime mode is not part of V1.

- [ ] **Step 3: Sanitize JobHunter evidence**

Record only dates, console/Hermes version hashes, gate outcomes, event names, timing ranges, device/browser classes, and confirmation that Hermes source plus workspace status were unchanged. Do not include OAuth state files, Clerk IDs, tailnet addresses, private prompts/responses, approval arguments, or keys.

- [ ] **Step 4: Run a public-history secret audit**

Run a working-tree scanner and a history scanner before making the repository public. Review every finding; do not merely suppress it. Confirm build output and `.env` files are ignored.

- [ ] **Step 5: Run final acceptance**

Run:

```bash
make test-all
. .venv/bin/activate && ruff check backend tests/backend
git diff --check
git status --short
```

Then repeat the JobHunter laptop and phone acceptance path from the approved design. Expected: an allowed Clerk user can speak, see Hermes work, hear the answer, approve or deny, stop, cancel speech independently, and reconnect without duplicate or accidental cancellation.

- [ ] **Step 6: Tag the standalone release before any upstream PR**

Create the release only after CI and live acceptance are green. Publish the container image from the same commit. Then open a small Hermes upstream PR that documents this standalone API Server frontend; do not move the console into Hermes or propose a source integration in the same PR.

- [ ] **Step 7: Commit the release documentation**

Run: `git add LICENSE CONTRIBUTING.md SECURITY.md README.md docs && git diff --cached --check && git commit -m "Prepare standalone voice console release"`

Expected: commit succeeds only after the owner-selected license exists and the evidence is sanitized.

---

## Final Definition of Done

- [ ] Local backend, frontend, fake E2E, Ruff, build, container, and secret-scan gates pass.
- [ ] Production human auth uses Clerk; no human static-token form or URL credential remains.
- [ ] Optional service auth is server-configured, auditable, and absent from the UI.
- [ ] JobHunter's API Server runs on loopback with the existing profile, workspace, tools, model, memory, and Codex OAuth.
- [ ] No Hermes source change or JobHunter workspace mutation was required for the integration.
- [ ] Laptop and phone work through Tailscale HTTPS.
- [ ] Browser sleep/reconnect does not cancel or duplicate an accepted Hermes run.
- [ ] Approval, stop-run, and cancel-speech behaviors are distinct and verified.
- [ ] A fresh Python install and fresh container install both work.
- [ ] The standalone repository is safe to publish and has a tagged release before upstream outreach.
