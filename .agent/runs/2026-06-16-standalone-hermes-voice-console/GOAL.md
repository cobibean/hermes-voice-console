# Build Standalone Hermes Voice Console

## Objective

Build the Standalone Hermes Voice Console end-to-end in `/root/DEV/hermes-voice-console` as its own web app/backend service that talks to Hermes agents through official Hermes API Server surfaces.

## Finishing Criteria

- No Hermes source checkout is patched, edited, vendored, or mirrored.
- Backend package implements config, auth, WebSocket voice protocol, recording bounds, fake/real STT and TTS adapters, target registry, Hermes API client/transports, approval/stop, and temp-audio guards.
- Frontend React/TypeScript app implements target/session selection, push-to-talk UI, transcript/run timeline, approval modal, playback queue/cancel, diagnostics, and errors.
- Backend tests, frontend lint/typecheck/tests/build, and fake E2E pass with exact commands recorded.
- Operator docs cover quickstart, config, target API Server setup, security, manual smoke, troubleshooting, rollback/uninstall.
- Real manual browser/mic/STT/TTS smoke is either completed or explicitly left as the final gate with missing prerequisites identified.

## Runtime Goal Coupling

Primary ledger: `.agent/runs/2026-06-16-standalone-hermes-voice-console/implementation-notes.html`

## Parent Goal

Standalone companion pivot from Hermes browser-voice source patch to `/root/DEV/hermes-voice-console`.

## Escape Hatch

Pause and ask before any action that would modify `/root/.hermes/hermes-agent`, `/root/DEV/review/hermes-agent-c20818a-review`, a deployed Hermes checkout, or production gateway services. If provider credentials, mic, browser, or real Hermes API Server target are unavailable, complete fake verification and leave real manual smoke as the final gate.

## Safety Constraints and Protected Paths

- Protected: `/root/.hermes/hermes-agent`, `/root/DEV/review/hermes-agent-c20818a-review`, deployed Hermes checkouts/services.
- Reference-only: `/root/DEV/review/hermes-voice-feature-c20818a`, commit `c20818a15b2a7626ff08f3691b238509e626537c`.
- Secrets must remain in `.env`/process env and never in YAML, frontend payloads, logs, commits, or ledger evidence.
- Console binds to `127.0.0.1` by default; remote mic requires HTTPS/Tailscale Serve or equivalent.
