# Voice Console Configuration

## Files

- `config/voice.example.yaml` — non-secret server and voice-provider settings.
- `config/targets.example.yaml` — target registry with env-var names for API keys.
- `.env.example` — secret/env names only. Copy to `.env` locally; never commit populated `.env`.
- `config/voice.fake.yaml` and `config/targets.fake.yaml` — deterministic fake provider/target configs for local smoke tests.

## Console auth

`server.auth_required` defaults to `true`. When enabled, set:

```bash
VOICE_CONSOLE_SESSION_SECRET=$(openssl rand -hex 32)
```

The frontend asks for this token and sends it to the standalone console only. It is not a Hermes target API key.

## Target keys

Each target references an env var name:

```yaml
targets:
  knwldg:
    base_url: "http://127.0.0.1:8642"
    api_key_env: "KNWLDG_API_SERVER_KEY"
```

Set the value in `.env` or the service environment:

```bash
KNWLDG_API_SERVER_KEY=...
```

The backend sends the key as `Authorization: Bearer <target-key>` to the Hermes API Server. The key is never included in `/api/bootstrap`, `/api/targets`, WebSocket ready frames, or frontend state.

## Voice providers

STT providers:

- `fake` — deterministic tests and local fake E2E.
- `openai` — uses `OPENAI_API_KEY` or `VOICE_TOOLS_OPENAI_KEY` with `/v1/audio/transcriptions`.
- `groq` — uses `GROQ_API_KEY` with Groq's OpenAI-compatible transcription endpoint.
- `faster_whisper` — optional local dependency; install separately if needed.

TTS providers:

- `fake` — deterministic valid WAV output.
- `edge` — uses optional `edge-tts`; no API key, network provider.
- `openai` — uses `OPENAI_API_KEY` or `VOICE_TOOLS_OPENAI_KEY` with `/v1/audio/speech`.
- `elevenlabs` — uses `ELEVENLABS_API_KEY` and `elevenlabs_voice_id`.

## Safety bounds

- `max_recording_seconds` limits audio duration by expected PCM byte count.
- `max_recording_wall_seconds` limits silent/slow clients that hold recording open.
- `max_buffer_mb` is the absolute recording buffer cap.
- `max_tts_text_chars` limits TTS prompt length.
- `max_tts_audio_mb` rejects oversized provider output.
- `retain_audio_debug` defaults false; leave it off except for targeted debugging.
