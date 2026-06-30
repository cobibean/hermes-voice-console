# Build Goal Slash Prompt

Paste this into a Hermes session from the repository root (`/root/DEV/hermes-voice-console`) when ready to implement.

```text
/goal Build the Standalone Hermes Voice Console end-to-end in /root/DEV/hermes-voice-console.

Context and source of truth:
- The implementation plan is /root/DEV/hermes-voice-console/docs/standalone-voice-console-plan.md. Read it first and treat it as the product spec.
- This is Option A: a standalone voice console outside the Hermes source tree.
- Do NOT patch, edit, vendor, or mirror the Hermes source tree. Do NOT modify /root/.hermes/hermes-agent, /root/DEV/review/hermes-agent-c20818a-review, or any deployed Hermes checkout.
- The prior Hermes browser-voice source-patch drop is reference only: cobibean/hermes-voice-feature@feat/v2-hermes-native commit c20818a15b2a7626ff08f3691b238509e626537c, local reference /root/DEV/review/hermes-voice-feature-c20818a.
- Reuse lessons from that reference: audio protocol, recording bounds, turn-id validation, playback queue/cancel pitfalls, TTS temp-file hardening, manual smoke criteria. Do not copy the source-patch architecture.

High-level product target:
- A standalone web app + backend that lets cobibean talk by voice to configured Hermes agents.
- Browser mic -> standalone backend STT -> Hermes API Server target -> structured response events -> standalone backend TTS -> browser playback.
- Agent turns must go through Hermes' official API Server surfaces, primarily /v1/capabilities, /v1/runs, /v1/runs/{run_id}/events, /v1/runs/{run_id}/approval, /v1/runs/{run_id}/stop, and optionally /api/sessions/{session_id}/chat/stream.
- The console must never instantiate Hermes agent internals directly and must never bypass Hermes approvals/tools/memory/session behavior.
- API server enablement on Hermes targets is allowed as a config/service step, but Hermes source patches are not allowed.

Mandatory workflow:
1. Load relevant skills: hermes-agent, software-development-lifecycle, github-workflows, goal-ledger, project-memory if useful.
2. Create/update a goal ledger under .agent/ for this implementation before coding. Keep it current after each phase and before/after any live smoke.
3. Inspect the plan and reference files before coding.
4. Implement in small verified phases. Do not stop at stubs. Each phase must have working code and tests or an explicitly documented blocker.
5. Prefer enterprise-grade v1: real error handling, auth, config, tests, docs, fake E2E, and operator handoff.
6. Use fake providers and a fake Hermes API Server target for deterministic tests before attempting real provider/agent smokes.
7. Do not expose or print secrets. Use .env and example config with env-var names only.

Required implementation deliverables:
- Python backend package for the voice console, likely FastAPI/uvicorn.
- React/TypeScript frontend, likely Vite.
- Config examples: target registry and voice/provider config.
- Server-side auth/session gate for the console.
- WebSocket voice protocol: hello, recording.start, binary audio, recording.stop, agent run events, approval.resolve, agent.stop, tts.cancel, ping/pong, error frames.
- Recording state machine with required turn_id, safe charset/length, byte cap, wall-clock cap, idle timeout, buffer clear after stop.
- STT adapters: fake provider for tests plus at least one real provider path documented and implemented where dependencies/keys allow.
- TTS adapters: fake provider for tests plus at least one real provider path documented and implemented where dependencies/keys allow.
- Owned temp audio directory and guards: regular files only, max size, delete only files the console owns.
- Hermes API target client: capability probe, health, server-side API key handling, runs transport with event stream, approval, stop, and optional session chat stream transport if useful.
- Frontend target/session picker, push-to-talk mic UI, transcript display, run timeline, approval modal, playback queue, cancel/stop controls, diagnostics/errors.
- Playback must be sequential, generation-aware, and cancellation-safe. Late chunks/events from canceled turns must not play.
- Tests: backend unit tests, frontend unit/state-machine tests, fake target integration tests, and fake E2E/smoke script.
- Docs: README quickstart, configuration guide, target API Server setup guide, security notes, manual smoke checklist, troubleshooting, rollback/uninstall.

Verification gates:
- Backend: run pytest. Include tests for protocol validation, recording caps, STT/TTS fake providers, target API client, approval/stop flow, temp-file guards, auth rejects.
- Frontend: run package install, lint, typecheck, tests, and production build.
- Fake E2E: one command starts fake target + backend and proves a full fake voice/text run through the UI or API path.
- Real smoke, if the environment has a reachable Hermes API Server target plus mic/STT/TTS credentials: run a localhost or HTTPS/Tailscale Serve browser smoke and record results. If not available, state exactly what is missing and leave real manual smoke as the only remaining gate.
- At the end, git status must be clean except intentionally uncommitted artifacts if the user asked not to commit. Prefer commit verified implementation locally after a secret scan.

Definition of done:
- No Hermes source tree was modified.
- The standalone repo contains a working voice console artifact, not just a plan.
- A fake E2E proves the full flow without external services.
- Tests/builds pass with exact commands recorded.
- Operator docs are sufficient for cobibean to configure one real Hermes target.
- Manual real smoke is either passed and documented or explicitly blocked by missing mic/provider/target access.
- The .agent ledger and final handoff identify current state, verification, remaining gates, and safe next action.
```
