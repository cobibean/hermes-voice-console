# Security Notes

## Trust boundaries

- Browser talks only to the standalone voice console backend.
- Voice console backend talks to Hermes targets through API Server.
- Hermes remains the only agent runtime; the console does not import or instantiate Hermes internals.
- Hermes approvals are not bypassed. Approval requests are surfaced to the UI and resolved through `/v1/runs/{run_id}/approval`.

## Secrets

- Secrets live in `.env`, systemd `EnvironmentFile`, or process env.
- YAML stores env-var names, not secret values.
- Frontend payloads contain target labels, base URLs, session keys, capabilities, and event payloads; they do not contain API keys.
- Logs and user-visible errors sanitize likely credential-bearing provider errors.

## Network exposure

Default bind is `127.0.0.1`. For remote microphone access, browsers require a secure context. Prefer Tailscale Serve HTTPS or a trusted local reverse proxy. Do not bind `0.0.0.0` without TLS and auth.

## Audio data

- PCM recordings are buffered in memory with byte and wall-clock caps.
- STT WAV temp files and TTS outputs are created in a console-owned temp directory.
- Files are mode `0600`; temp directory is mode `0700` where supported.
- By default files are deleted after use. `retain_audio_debug` should remain false unless debugging.

## Known V1 limitations

- Push-to-talk/half-duplex only; no full-duplex barge-in.
- TTS cancellation is best-effort once a provider request is already in flight.
- Real provider behavior must be manually smoked in the deployment environment.
