# Remote Rollout Next Steps

Use this when the Hermes agents move onto the Mac mini and the voice console is ready for real-world testing from a phone or laptop.

## 1. Set Up Remote Access First

Goal: expose the voice console over HTTPS while keeping raw Hermes API Server targets private.

Preferred shape:

```text
phone/laptop browser
  -> Tailscale Serve HTTPS URL
  -> Hermes Voice Console on the Mac mini
  -> local Hermes API Server targets on the Mac mini
```

Do not expose individual Hermes API Server ports to the public internet. The browser should only reach the voice console. The console should hold target API keys server-side and call Hermes targets over `127.0.0.1`, LAN, or tailnet-private addresses.

Recommended first pass:

1. Install and sign in to Tailscale on the Mac mini.
2. Enable Tailscale HTTPS for the tailnet if it is not already enabled.
3. Run each Hermes agent with API Server enabled and a unique `API_SERVER_KEY`.
4. Configure `config/targets.yaml` so local Mac mini agents use `http://127.0.0.1:<agent-port>` as `base_url`.
5. Configure `.env` with `VOICE_CONSOLE_SESSION_SECRET`, provider keys, and each target's API key env var.
6. Build the frontend: `cd frontend && pnpm build`.
7. Run the console locally on the Mac mini: `voice-console serve --config config/voice.yaml --targets config/targets.yaml`.
8. Publish the local console to the tailnet with Tailscale Serve, for example: `tailscale serve --bg 8787`.
9. Confirm `tailscale serve status` shows the voice console endpoint.
10. Open the HTTPS tailnet URL from a phone and laptop, then unlock with `VOICE_CONSOLE_SESSION_SECRET`.

Keep `server.auth_required: true`. Leave the console bound to `127.0.0.1` unless a trusted reverse proxy requires otherwise. If public internet access is ever needed for non-tailnet devices, treat Tailscale Funnel or another public proxy as a separate security review, not the default path.

## 2. Run Real Smoke Tests

Start with fake proof, then one non-critical real target.

Automated baseline:

```bash
source .venv/bin/activate
pytest tests/backend -q
cd frontend
pnpm lint
pnpm typecheck
pnpm test
pnpm build
cd ..
voice-console fake-e2e
```

Real remote smoke:

1. Open the HTTPS tailnet URL from the laptop.
2. Unlock with the console token.
3. Select a non-critical Hermes target.
4. Probe target health and confirm `/v1/capabilities` reports structured run support.
5. Hold push-to-talk, speak a harmless prompt, release.
6. Confirm transcript quality, run timeline events, final response, and optional TTS playback.
7. Repeat from a phone browser over cellular or another non-home network.
8. Test cancel speech during playback.
9. Test stop run during a safe long-running command.
10. Test one approval-producing prompt and verify `once` and `deny`.
11. Test wrong target key and unconfigured provider failures to confirm errors are clear and secrets do not leak.

Record results in a dated note under `docs/memory/` or `.agent/runs/` with:

- device/browser;
- network path;
- target name, but not secret keys;
- STT and TTS providers;
- pass/fail for mic, transcript, run events, TTS, cancel, stop, approval, auth failure, and provider failure;
- any awkward UI moments.

## 3. Iterate On Product Behavior

Only iterate after the remote smoke path is trustworthy.

Likely first improvements:

1. Make target/session switching feel safer, especially when a run is active.
2. Improve status language around connecting, transcribing, running, waiting for approval, speaking, and stopped.
3. Add better provider diagnostics for STT/TTS setup without exposing secrets.
4. Add a clearer remote-ready checklist to the UI or docs if setup still feels fiddly.
5. Decide whether session history should remain ephemeral or get a small local persistence layer.
6. Decide whether multi-agent switching needs groups, favorites, or recent targets.

## 4. Design A Better UI

The current UI is functional enough for smoke testing. A design pass should happen after real use shows which states matter most.

Design direction:

- Treat it like a focused operator console, not a generic chat app.
- Make the active target, session, mic state, run state, and approval state impossible to miss.
- Keep push-to-talk central and thumb-friendly on mobile.
- Make the run timeline scannable but not noisy.
- Give approvals a high-trust modal with clear action labels.
- Keep diagnostics available without making the main screen feel like a debug panel.
- Make TTS playback/cancel feel immediate and obvious.

Useful UI pass order:

1. Mobile-first voice screen.
2. Desktop command-center layout.
3. Target/session drawer.
4. Timeline and transcript visual hierarchy.
5. Approval and failure states.
6. Dark/light theme and basic motion polish.

## 5. Later Hardening

After remote voice chat works reliably:

- Add a launchd service example for macOS in addition to the current systemd example.
- Add a Mac mini setup checklist.
- Consider stricter token rotation instructions for `VOICE_CONSOLE_SESSION_SECRET`.
- Add browser compatibility notes for iOS Safari, Chrome, and desktop Safari.
- Add optional HTTPS reverse-proxy docs for users not using Tailscale.
- Consider audit logging for target selection, approval decisions, and stop requests without storing private transcript/audio by default.

## Current Decision

The next real project milestone is not more core implementation. It is:

1. Mac mini migration.
2. Tailscale Serve HTTPS access.
3. Real mic/STT/TTS/live-Hermes smoke from phone and laptop.
4. UX/UI iteration based on what feels clumsy during that smoke.
