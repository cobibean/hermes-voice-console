# Hermes Voice Console Phase 7 Memory - 2026-07-12

## Session summary

Closed Phase 7 of the approved V1 implementation plan. The pinned standalone console is deployed beside JobHunter, available only through a new tailnet HTTPS endpoint, protected by Clerk for the single allowed human plus a separate service credential, and approved at the first desktop usability gate.

## Deployment

- Live tailnet URL: `https://job-hunter.tailf1a3a1.ts.net:9443/`.
- Deployed revision and image: `1b0bc81` / `hermes-voice-console:1b0bc81`.
- Deployment root: `/opt/hermes-voice-console`; pinned releases live beneath `releases/`, with `app` pointing to the active release.
- Docker Compose uses host networking so the console can reach loopback-only Hermes on 8642.
- The console binds only `127.0.0.1:8788`; Hermes remains on `127.0.0.1:8642`.
- Tailscale Serve proxies only HTTPS 9443 to loopback 8788. Raw 8642 and 8788 were unreachable over the tailnet.
- Roll back only the new endpoint with `tailscale serve --https=9443 off`.
- Before/after Serve evidence is stored with owner-only permissions under `/opt/hermes-voice-console/evidence`.
- Canonical comparison showed only `TCP.9443` and `Web.job-hunter.tailf1a3a1.ts.net:9443` were added; existing Serve handlers were unchanged.

## Clerk and authentication

- Clerk CLI 2.1.0 was installed, authenticated, and linked to the existing development application.
- The frontend already had runtime `ClerkProvider`, sign-in, and account controls. CLI-generated provider scaffolding was declined to avoid a duplicate provider and build-time credential coupling.
- Added an explicit **Create account** action and test coverage.
- The first development user was created through the live console and is now the sole allowed human account. The raw user ID and credentials are intentionally omitted here.
- Clerk issuer/JWKS validation passed before deployment.
- Temporary local Clerk environment files were mode `0600` and removed after use. No Clerk secret was copied into the repository or droplet.
- Corrected the backend so Clerk human auth and the optional service credential coexist, matching the approved plan. Programmatic clients may omit `Origin`; supplied origins remain exact-allowlisted.

## Verification

- Container is running healthy as UID 10001 with zero restarts after final configuration.
- Mutable state is mode `0700` and owned by UID/GID 10001; deployment secrets are mode `0600`.
- HTTPS frontend and public Clerk configuration returned 200; unauthenticated bootstrap returned 401.
- Service-authenticated HTTPS bootstrap, secure WebSocket authentication, owned conversation creation, and a real JobHunter text turn passed through the production URL.
- After the single-user Clerk lock, the container remained healthy and service authentication still passed.
- Local verification at the deployed commit: Ruff passed, 39 backend tests passed, and 7 frontend files / 19 tests plus lint, typecheck, and build passed.
- Repository `main` and `origin/main` matched before the human gate.

## Desktop usability gate

- User approved New Conversation, multi-turn nonce recall, tool activity visibility, and explicit Stop behavior.
- The harmless delete-like approval probe did not surface an approval event. Hermes smart approval flagged and auto-approved it upstream, so the console had no unresolved approval to display.
- Record live approval denial as **not exercised**, not failed. Do not escalate to a more dangerous command merely to force the UI.
- Deterministic frontend/backend tests continue to cover the console's approval presentation and decision path.

## Gotchas and constraints

- Current deployment still uses fake STT and fake TTS; real turn-based voice begins in Phase 8.
- Tailscale Serve configuration must be changed surgically. Never use `tailscale serve reset` on this host.
- Production WebSockets require WSS. Direct loopback `ws://` rejection under the public non-loopback configuration is expected.
- The container image healthcheck defaults to 8787, so the JobHunter Compose deployment overrides it to the actual loopback port 8788.
- Live approval behavior depends on Hermes policy. Smart approval can resolve a command before the console receives an approval event.

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`
