# Voice Console Configuration

## Files

- `config/voice.example.yaml` - non-secret server, auth-policy, and voice-provider settings.
- `config/targets.example.yaml` - target registry with env-var names for API keys.
- `.env.example` - secret/env names only. Copy to `.env` locally; never commit populated `.env`.
- `config/voice.fake.yaml` and `config/targets.fake.yaml` - deterministic loopback development configs.

## Authentication modes

`auth.mode` is explicit and must be one of:

- `clerk` - interactive human access. Configure an exact HTTPS issuer, publishable key, exact allowed origins, and optional allowed user IDs. The publishable key is the only Clerk value returned by `/api/public-config`.
- `service` - programmatic-only access. Set the env var named by `auth.service_token_env`, normally `VOICE_CONSOLE_SERVICE_TOKEN`. The browser shows an informational screen and never asks for this token.
- `development` - credential-free local interaction. Startup fails unless both the bind host and `public_base_url` are loopback. Never place this mode behind Tailscale or another proxy.

Every mode requires a separate ownership secret:

```bash
VOICE_CONSOLE_SCOPE_SECRET=$(openssl rand -hex 32)
```

The backend uses this secret to derive stable pseudonymous owner and memory-scope keys. Rotating it intentionally changes those keys and makes previously owned console sessions/runs inaccessible through their old ownership mapping. Do not reuse a Clerk secret, service token, Hermes key, or speech-provider key.

Service mode additionally requires:

```bash
VOICE_CONSOLE_SERVICE_TOKEN=$(openssl rand -hex 32)
```

HTTP clients use `Authorization: Bearer`. WebSocket clients connect with no credentials in the URL and send an `auth` frame first. Browser code never stores JWTs or service tokens in `localStorage` or `sessionStorage`.

## Exposure policy

- `server.public_base_url` must be HTTPS outside loopback.
- `server.allowed_hosts` and `auth.allowed_origins` are exact allowlists; wildcards are not supported.
- Clerk and development browser WebSockets require an allowed `Origin`.
- A service client may omit `Origin`; if it supplies one, that origin must be allowed.
- Non-loopback WebSockets must arrive as WSS after trusted proxy headers are applied.
- `auth.allow_persistent_approvals` defaults false and can only narrow Hermes' event-level permission.

## Target keys and labels

Each target references an env var name. Its private `base_url` remains server-only:

```yaml
targets:
  jobhunter:
    base_url: "http://127.0.0.1:8642"
    api_key_env: "JOBHUNTER_API_SERVER_KEY"
    configured_provider_label: "Codex OAuth"
    configured_model_label: "Operator configured model"
```

Provider/model labels are optional operator-configured descriptions, not proof of the model that executed a particular run. Target keys and target base URLs are never included in browser DTOs.

## Voice providers

STT providers are `fake`, `openai`, `groq`, and optional local `faster_whisper`. TTS providers are `fake`, `edge`, `openai`, and `elevenlabs`. Provider credentials stay in the console service environment.

## Safety bounds

- `max_recording_seconds` limits audio duration by expected PCM byte count.
- `max_recording_wall_seconds` limits silent/slow clients that hold recording open.
- `max_buffer_mb` is the absolute recording buffer cap.
- `max_tts_text_chars` limits TTS prompt length.
- `max_tts_audio_mb` rejects oversized provider output.
- `server.max_ws_text_chars` limits authenticated text frames.
- `auth.preauth_max_chars` and `auth.auth_timeout_seconds` bound pre-authentication work.
- `retain_audio_debug` defaults false; leave it off except for targeted debugging.
