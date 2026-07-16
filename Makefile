.PHONY: check browser-check realtime-upgrade-gate realtime-staging-gate realtime-rollback-gate build-image smoke-stack smoke-stack-down

check:
	.venv/bin/ruff check backend tests/backend
	.venv/bin/python -m pytest tests/backend -q
	cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
	.venv/bin/python scripts/realtime_security_gate.py
	.venv/bin/voice-console fake-e2e

realtime-upgrade-gate:
	.venv/bin/python scripts/realtime_upgrade_gate.py --hermes-repo "$${HERMES_REALTIME_REPO:?set HERMES_REALTIME_REPO}"

realtime-staging-gate:
	.venv/bin/python scripts/realtime_rollout_gate.py --mode staging --target "$${HERMES_REALTIME_TARGET:?set HERMES_REALTIME_TARGET}" --targets "$${HERMES_REALTIME_TARGETS:?set HERMES_REALTIME_TARGETS}" --supported-hermes-repo "$${HERMES_REALTIME_REPO:?set HERMES_REALTIME_REPO}" --current-main-repo "$${HERMES_CURRENT_MAIN_REPO:?set HERMES_CURRENT_MAIN_REPO}" --current-main-sha "$${HERMES_CURRENT_MAIN_SHA:?set HERMES_CURRENT_MAIN_SHA}"

realtime-rollback-gate:
	.venv/bin/python scripts/realtime_rollout_gate.py --mode rollback --target "$${HERMES_REALTIME_TARGET:?set HERMES_REALTIME_TARGET}" --targets "$${HERMES_REALTIME_TARGETS:?set HERMES_REALTIME_TARGETS}"

browser-check:
	cd frontend && pnpm build && pnpm test:e2e

build-image:
	docker build -t hermes-voice-console:local .

smoke-stack:
	docker compose -f deploy/compose.example.yaml up --build --wait

smoke-stack-down:
	docker compose -f deploy/compose.example.yaml down --volumes --remove-orphans
