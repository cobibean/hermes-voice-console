# Phase 0 Realtime Baseline Memory — 2026-07-15

## Scope

Lock clean Voice Console and Hermes evidence before implementing the GPT-Realtime-2.1 runtime plan.

## Source of truth

- Design: `docs/plans/2026-07-15-gpt-realtime-2-1-hermes-runtime-design.md`
- Implementation plan: `docs/plans/2026-07-15-gpt-realtime-2-1-hermes-runtime-implementation-plan.md`
- Voice Console branch: `codex/gpt-realtime-hermes-runtime`
- Plan commit: `1dbc511`
- Upstream research base: `00a36831d214488f901df7de71efde02a8072aa4`
- Upstream implementation base: `0c1adb4877f344af8276d5277871e8056cef3ad5`

## Verified baseline

- `make check` passed.
- Ruff passed.
- Backend pytest passed: 44 tests.
- Frontend lint and typecheck passed.
- Frontend Vitest passed: 9 files and 25 tests.
- Frontend production build passed.
- Fake end-to-end protocol check passed.
- `make browser-check` passed.
- Playwright passed: 7 tests.
- The configured server credential can access `gpt-realtime-2.1`.
- The same credential can access `gpt-5.6-sol`, `gpt-5.6-luna`, and `gpt-5.6-terra`; a bare `gpt-5.6` model ID is unavailable.
- `gpt-5.6-sol` is the initial configuration-driven lead-worker default.

## Installed Hermes evidence

- Installed Hermes reports v0.18.2, release `2026.7.7.2`, upstream commit `111544d5`.
- The installed checkout is behind current upstream and contains a large untracked working set.
- The installed checkout is not a safe development or update target.
- Its API capabilities advertise `realtime_voice: false`.
- Its runtime modes do not include a Realtime transport.
- Its local gateway is stopped and no local API Server is listening on port 8642.
- The default local profile has no model/provider or OpenAI/API Server credential configured.

## Environment boundaries

- Realtime development happens in a clean sibling Hermes checkout, not the installed checkout.
- The existing Voice Console `.env` remains local and unmodified.
- No credential value is copied into source, documentation, phase memory, logs, or the sibling checkout.
- The local OpenAI credential may be loaded only at live-smoke process runtime.
- Real `config/voice.yaml` and `config/targets.yaml` are not present in this checkout; fake/example configuration remains the automated-test path.
- No production Hermes update, gateway start, deployment, or external pull request is authorized by Phase 0.

## Gate status

Phase 0 automated baselines are green. Phase 1 proceeds in the clean sibling Hermes checkout. Realtime remains disabled in the compatibility manifest until fake contract, live Realtime, and live delegation evidence pass.

## Next gate

Prove unified SDP bootstrap, controller-ready sideband fencing, one harmless Hermes tool call, one background `gpt-5.6-sol` delegation, approval authority, completion delivery, and reconnect behavior without copying the Hermes agent loop.
