# Hermes Target API Server Setup

The voice console uses Hermes' API Server adapter. Enabling API Server is a Hermes configuration/service step, not a Hermes source patch.

## Required Hermes target surface

The target must expose:

- `GET /v1/capabilities`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}/events`
- `POST /v1/runs/{run_id}/approval`
- `POST /v1/runs/{run_id}/stop`
- `GET /health`

The console probes `/v1/capabilities` during the WebSocket `hello` flow and fails closed with `target_capability_missing` if structured runs/events are not available.

## Target auth

Hermes API Server requires `API_SERVER_KEY`; the console sends it as a bearer token. Use a unique key per target where practical.

Example target config:

```yaml
targets:
  knwldg:
    label: "knwldg"
    base_url: "http://127.0.0.1:8642"
    api_key_env: "KNWLDG_API_SERVER_KEY"
    default_session_key: "voice-console:knwldg"
    preferred_transport: "runs"
```

## Session identity

The console sends both:

- request body `session_id`, for Hermes short-term/API run continuity;
- `X-Hermes-Session-Key`, for stable API-server gateway/memory scoping.

By default both use the target's `default_session_key`, but the browser UI lets the operator edit the session key for a specific conversation.

## Verification

From the console host, with the target key loaded:

```bash
curl -sS -H "Authorization: Bearer <target-api-server-key>" http://127.0.0.1:8642/v1/capabilities
```

Then use the console diagnostics endpoint:

```bash
curl -sS -H "Authorization: Bearer <console-session-secret>" http://127.0.0.1:8787/api/targets/knwldg/health
```

Do not expose either API Server or the voice console publicly without HTTPS and auth.
