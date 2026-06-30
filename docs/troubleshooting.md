# Troubleshooting

## Browser says microphone unavailable

- Use `localhost`, `127.0.0.1`, or HTTPS/Tailscale Serve. Plain HTTP over a remote hostname is not a secure context.
- Confirm browser permission prompts are allowed.
- Confirm the browser supports `AudioWorkletNode`.

## WebSocket closes immediately

- Check `VOICE_CONSOLE_SESSION_SECRET` and the token entered in the UI.
- Check server logs for `4401` auth failures.
- If auth is disabled for local development, verify `server.auth_required: false` in the active config.

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
