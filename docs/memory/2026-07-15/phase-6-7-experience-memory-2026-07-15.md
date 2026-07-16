# Phase 6-7 Realtime Experience Memory

**Date:** 2026-07-15

**Status:** Frontend transport, manual controls, and presentation gates passed

## Pinned upstream

- Hermes manual turn-mode and commit: `351da78c98564002effa32d57f5c8fd2fedfa1e9`
- Hermes approval identity and worker command results: `810ac2b946aeaddffa2a5d7e91035ec8505c9ec4`
- Hermes authoritative manual discard and verified head: `d41e793a355ae1bb9dc2c974d1fd2edc8b6c6a61`

## Voice Console commits

- Realtime presentation foundation: `3fa4463`
- Presentation trust remediation: `d26a497`
- Dual Realtime and legacy transports: `8e8f09c`
- Transport recovery and control hardening: `ab9eb80`
- Frozen worker command alignment: `a8c7869`
- Durable approval identity: `09b281b`
- Authoritative manual commit: `28a52b3`
- Manual capture UI: `cfafed1`
- Manual identity and compatibility fencing: `f3b0a7f`
- Manual discard presentation guard: `39e7f00`
- Proxy manual discard: `43e85ac`
- Authoritative discard transport: `ba0dda8`
- Rejected mode propagation and degraded recovery: `97806eb`, `f1e1234`
- Final recovery microphone guard and verified Voice head: `7870173`

## Product behavior now verified

- Realtime and legacy voice are independent state machines under one shared conversation controller.
- Realtime becomes live only when browser media and the authenticated Hermes control snapshot are both ready.
- Exactly one active peer, microphone capture, control socket, and transport survives responsive shell changes.
- Reconnect restores authoritative snapshot state, resumes newer event IDs, and never redispatches durable jobs.
- Hermes remains the sole conversational persona while delegated workers appear as inline jobs, tools, approvals, artifacts, verification, and results.
- Worker refine, redirect, and cancel use exact durable acknowledgements and revisions.
- Approval UI restores the authoritative tool name and expiration without exposing arguments.
- End Call and Legacy fallback close only the ephemeral Realtime transport; durable jobs remain available after reconnect.
- Manual mode is server-authoritative. Start recording explicitly unmutes, Send mutes before committing, and Discard waits for OpenAI's authoritative buffer-clear acknowledgement.
- Manual commit, discard, mute, interruption, worker cancellation, mode switching, fallback, reconnect, and End Call are distinct operations.
- Duplicate taps, stale acknowledgements, target/conversation changes, and ambiguous provider outcomes fail closed.
- Rejected or uncertain manual operations lock the session degraded until a new Realtime generation is created.
- Desktop and mobile share the same accessible controls, 44-pixel touch targets, Legacy fallback, recovery actions, and job presentation.
- Artifact links are restricted to app-owned artifact paths or explicitly trusted HTTPS origins.

## Independent gate evidence

- Phase 7 presentation: passed in isolated committed snapshot.
- Phase 5.2 plus Phase 6 core: passed end to end.
- Phase 5.3 plus Phase 6.1-6.2 plus Phase 7.2: definitive pass.
- Final Voice Console `make check`: Ruff, all backend tests, frontend lint/typecheck, 91 frontend tests, production build, and fake E2E passed.
- Hermes manual/discard focused verification and credentialed live WebRTC clear-to-fresh-commit proof passed.

## Next gate

Phase 8 must perform real browser recovery/security/upgrade acceptance and the visual quality pass. Capture desktop and mobile screenshots for live conversation, active worker, approval, blocked/recovery, manual capture, and completed artifact states. The chosen visual direction should be modern, minimal, and distinctly inspired by the current official Nous Research/Hermes Agent language without copying the marketing site literally.
