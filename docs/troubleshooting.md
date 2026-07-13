# Troubleshooting

## Browser says microphone unavailable

- Use `localhost`, `127.0.0.1`, or HTTPS/Tailscale Serve. Plain HTTP over a remote hostname is not a secure context.
- Confirm browser permission prompts are allowed.
- Confirm the browser supports `AudioWorkletNode`.

## WebSocket closes immediately

- A `4401` indicates missing, invalid, or expired Clerk/service authentication.
- A `4403` indicates a valid but unauthorized Clerk user, disallowed Host/Origin, or insecure non-loopback WebSocket.
- In Clerk mode, verify the exact issuer, authorized origin, allowed user list, and Clerk dashboard origin.
- In service mode, verify the bearer/frame credential from `VOICE_CONSOLE_SERVICE_TOKEN`; never add it to a URL.
- In development mode, verify both bind host and public URL are loopback and the browser Origin is explicitly allowed.

## Target capability missing

- Confirm the Hermes target has API Server enabled.
- Confirm the target supports structured `/v1/runs` and `/v1/runs/{run_id}/events`.
- Run the `/api/targets/{name}/health` endpoint from the console.

## Invalid API key

- Confirm the env var named by `api_key_env` is present in the console process environment.
- Confirm it matches the Hermes target's `API_SERVER_KEY`.
- Do not paste the raw key in chat/logs; verify with redacted env status or a direct curl.

## STT/TTS provider failure

- `fake` providers should always work in tests.
- OpenAI STT/TTS uses `OPENAI_API_KEY` or `VOICE_TOOLS_OPENAI_KEY`.
- Groq STT uses `GROQ_API_KEY`.
- ElevenLabs TTS needs both `ELEVENLABS_API_KEY` and `elevenlabs_voice_id`.
- Edge TTS requires optional `edge-tts` and network access.

## Speech overlaps or resumes after cancel

This should be covered by the frontend playback queue tests. If reproduced manually, capture:

- browser;
- exact event sequence from the timeline;
- whether `tts.cancelled` appears;
- whether a stale `tts.end` arrived after cancel.
