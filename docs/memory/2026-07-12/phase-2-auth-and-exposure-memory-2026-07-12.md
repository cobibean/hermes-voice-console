# Hermes Voice Console Phase 2 Memory - 2026-07-12

## Session summary

Closed Phase 2 of the approved V1 implementation plan. Human, automation, and local-development authentication are now separate modes, browser credentials no longer enter URLs or web storage, and the HTTP/WebSocket exposure boundary is explicit and tested.

## What changed

- Added current `PyJWT[crypto]` 2.13.0 and `@clerk/react` 6.12.2.
- Added explicit `clerk`, `service`, and loopback-only `development` configuration modes.
- Added runtime unauthenticated `/api/public-config`; only auth mode, Clerk publishable key when applicable, and public base URL are exposed.
- Implemented Clerk RS256/JWKS verification with exact issuer, required time/subject claims, five-second skew, exact `azp` origin, and optional user allowlist.
- Implemented constant-time service-token comparison and a required separate scope secret for pseudonymous ownership.
- Replaced query/static browser-token auth with a bounded first WebSocket `auth` frame and HTTP bearer auth.
- Added expiry-driven Clerk refresh frames with principal continuity and expiry close behavior.
- Added exact Host/Origin checks, non-loopback HTTPS/WSS validation, pre-auth timeout/size limits, authenticated frame limits, and content-free pseudonymous audit identity.
- Removed target base URLs from browser DTOs and sanitized capability documents.
- Added optional configured provider/model labels and persistent-approval deployment policy, defaulting off.
- Replaced the human secret form with Clerk sign-in/account controls, a service-only notice, or a prominent development warning.
- Removed all frontend token storage helpers and documented scope-secret rotation consequences.

## Key files

- `backend/voice_console/auth.py`
- `backend/voice_console/config.py`
- `backend/voice_console/app.py`
- `backend/voice_console/voice_socket.py`
- `tests/backend/test_auth_phase2.py`
- `frontend/src/App.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/voiceClient.ts`
- `frontend/src/App.test.tsx`
- `docs/configuration.md`

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`

## Commands and verification

- `.venv/bin/pip install -e '.[dev]'` - editable environment refreshed with PyJWT crypto support.
- `.venv/bin/ruff check backend tests/backend` - passed.
- `.venv/bin/python -m pytest tests/backend -q` - 26 passed.
- `.venv/bin/voice-console fake-e2e` - service-frame authenticated full voice turn passed.
- `pnpm lint && pnpm typecheck && pnpm test && pnpm build` - passed; 6 Vitest files / 15 tests.
- Production bundle scan for legacy console-secret, service-token, token-query, and old storage-key patterns - clean.
- `git diff --check` - passed.

## Gotchas and constraints

- Clerk production credentials and exact deployment origin remain a Phase 7 human gate; Phase 2 uses generated RSA keys and an injected signing-key client for deterministic verification tests.
- `typescript@latest` resolved to TypeScript 7, which the current TypeScript-ESLint parser does not yet support. The frontend is pinned to compatible TypeScript 6.0.3 while other compatible packages remain current.
- Uvicorn must trust forwarded scheme/host headers only from the loopback reverse proxy in deployment; that process-level configuration lands in Phase 6.
- Scope-secret rotation changes pseudonymous ownership keys and intentionally severs access through prior console ownership mappings.
