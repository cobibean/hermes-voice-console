# Manual Real Smoke Checklist

Use this after backend tests, frontend tests/build, and fake E2E pass.

## Prerequisites

- Reachable Hermes API Server target with `/v1/capabilities` and `/v1/runs` support.
- Target `API_SERVER_KEY` stored in this console's `.env` under the configured `api_key_env`.
- Real STT provider configured and credentialed, or local faster-whisper installed.
- Real/free-ish TTS provider configured (Edge/OpenAI/ElevenLabs).
- Browser with microphone access in a secure context: `localhost` or HTTPS/Tailscale Serve.
- Speakers/headphones available.

## Steps

1. Build frontend: `cd frontend && pnpm build`.
2. Start the voice console with real config: `voice-console serve --config config/voice.yaml --targets config/targets.yaml`.
3. Open `http://localhost:8787` or the HTTPS/Tailscale Serve URL.
4. Sign in with Clerk, or confirm the loopback-only development warning for a local fake smoke. Service mode has no interactive browser console.
5. Select one non-critical Hermes target.
6. Click **Connect / probe target** and confirm diagnostics show connected and target ready.
7. Hold the mic button, speak a harmless prompt, release.
8. Confirm transcript appears and is correct enough to send.
9. Confirm Hermes run timeline shows started, deltas/tool events if any, and completed/failed status.
10. If **Speak replies** is enabled, confirm one sequential assistant playback with no overlap.
11. Press **Cancel speech** during playback; verify playback stops and stale chunks do not resume.
12. Press **Stop current Hermes run** during a safe long-running test; verify a stop event or clear error.
13. If a safe approval-producing prompt is available, verify approval modal and `once`/`deny` paths.
14. Trigger a target auth failure by temporarily using a wrong key; verify a clear target error without secret leakage.
15. Trigger a provider failure by selecting an unconfigured provider; verify a clear provider error without secret leakage.

## Record results

Record:

- date/time;
- target name and base URL class (localhost/Tailscale, not secret key);
- STT/TTS providers;
- browser and OS;
- pass/fail for mic, transcript, Hermes run, TTS playback, cancel, stop, approval, auth failure, provider failure;
- remaining limitations.

If any prerequisite is unavailable in the execution environment, fake E2E remains the automated proof and this manual smoke is the final gate.
