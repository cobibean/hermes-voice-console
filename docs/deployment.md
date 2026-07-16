# Portable Deployment

For GPT-Realtime-2.1 staging, supported-pin validation, physical-device acceptance, and rollback, follow [Realtime Rollout and Release Lane](realtime-rollout-and-release.md). Realtime remains target-scoped and disabled by default.

## Container contract

The image is a multi-stage Node/Python build. The final runtime contains no Node toolchain, runs as UID/GID `10001`, packages the built frontend inside the Python wheel, stores mutable state only under `/data`, and uses Python for its healthcheck.

Build and run the deterministic stack:

```bash
export VOICE_CONSOLE_SCOPE_SECRET="$(openssl rand -hex 32)"
export VOICE_CONSOLE_SERVICE_TOKEN="$(openssl rand -hex 32)"
docker compose -f deploy/compose.example.yaml up --build --wait
docker compose -f deploy/compose.example.yaml down --volumes --remove-orphans
```

The fake stack intentionally uses service mode so automated clients can prove HTTP/WebSocket protocol behavior without a human credential. Its browser page is expected to show the programmatic-only notice.

## JobHunter host-network layout

Use `deploy/compose.jobhunter.example.yaml` as a starting point. Its required invariants are:

- `network_mode: host`, because Hermes remains loopback-only on port 8642;
- one console process/worker;
- console bind `127.0.0.1:8788`, leaving the existing 8787 service untouched;
- state directory `/opt/hermes-voice-console/state` with owner-only permissions;
- absolute read-only config mounts;
- `restart: unless-stopped`;
- Tailscale Serve terminates HTTPS on a separate tailnet endpoint and forwards only to loopback.

Example non-secret server settings:

```yaml
server:
  host: "127.0.0.1"
  port: 8788
  public_base_url: "https://YOUR-TAILNET-HOST:9443"
  allowed_hosts: ["YOUR-TAILNET-HOST", "127.0.0.1", "localhost"]
  state_dir: "/data"

auth:
  mode: "clerk"
  clerk_publishable_key: "pk_test_PUBLIC_VALUE"
  clerk_issuer: "https://YOUR-CLERK-ISSUER"
  allowed_origins: ["https://YOUR-TAILNET-HOST:9443"]
  allowed_user_ids: ["YOUR_CLERK_USER_ID"]
```

Uvicorn is fixed to one worker and accepts forwarded scheme/host information only from `127.0.0.1`. Do not widen `forwarded_allow_ips`; Tailscale identity headers do not replace Clerk authentication.

## Optional speech dependencies

- Edge TTS: `pip install 'hermes-voice-console[edge]'`
- Local faster-whisper: `pip install 'hermes-voice-console[local-stt]'`

The base image includes the HTTP speech adapters and deterministic fake providers, but not these heavier optional runtimes.
