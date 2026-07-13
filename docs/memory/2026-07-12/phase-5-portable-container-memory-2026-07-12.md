# Hermes Voice Console Phase 5 Memory - 2026-07-12

## Session summary

Closed Phase 5 of the approved V1 implementation plan. A clean multi-stage container build and isolated fake Compose stack now prove the console can ship with packaged frontend assets, run non-root, persist owner-only metadata, execute its authenticated protocol, and shut down cleanly.

## What changed

- Added a Node 24 frontend build stage, Python 3.13 wheel stage, and slim non-root runtime image.
- Packaged the built frontend inside the Python wheel and added source/wheel/container static asset discovery.
- Added a Python-based container healthcheck, UID/GID 10001 runtime, and `/config` plus `/data` contracts.
- Added `.dockerignore`, Makefile targets, deterministic fake Compose stack, container smoke configs, and a host-network JobHunter example.
- Added explicit Edge TTS and local faster-whisper optional dependency groups.
- Fixed Uvicorn to one worker with proxy headers trusted only from loopback.
- Documented the portable container contract, fake smoke stack, JobHunter host-network invariants, and Tailscale reverse-proxy boundary.

## Key files

- `Dockerfile`
- `.dockerignore`
- `Makefile`
- `deploy/compose.example.yaml`
- `deploy/compose.jobhunter.example.yaml`
- `deploy/container-smoke/voice.yaml`
- `deploy/container-smoke/targets.yaml`
- `docs/deployment.md`
- `pyproject.toml`

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`

## Container verification

- Docker Desktop engine 29.6.1 and Compose 5.2.0 on Linux/arm64.
- Clean `docker build --pull --no-cache` passed.
- Final image size: 75,904,965 bytes.
- Runtime user: `10001:10001`.
- Frontend TypeScript/Vite build passed inside the image.
- Python wheel built inside the image and contained `index.html`, hashed JavaScript, and hashed CSS assets.
- `docker compose up --build --wait` brought both fake target and console to healthy state.
- Host `/health`, `/api/public-config`, and packaged frontend load passed.
- `/data` was mode `0700`; SQLite was mode `0600`, both owned by UID/GID 10001.
- Authenticated service-frame WebSocket smoke created an owned conversation and completed a typed Hermes run with all required events.
- Container logs contained no traceback/error/fatal matches.
- Compose stopped cleanly and removed both containers, network, and state volume.

## Full project verification

- `.venv/bin/ruff check backend tests/backend` - passed.
- `.venv/bin/python -m pytest tests/backend -q` - 37 passed.
- `.venv/bin/voice-console fake-e2e` - passed voice and typed turns.
- `pnpm lint && pnpm typecheck && pnpm test && pnpm build` - passed; 7 Vitest files / 19 tests.
- `git diff --check` - passed.

## Gotchas and constraints

- The fake Compose browser intentionally shows the service/programmatic-only notice; interactive Clerk deployment begins in Phase 7.
- JobHunter deployment requires host networking because Hermes remains loopback-only on port 8642.
- The application remains a one-worker V1 until shared multi-process run coordination is designed.
