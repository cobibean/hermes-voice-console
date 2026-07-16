.PHONY: check browser-check realtime-upgrade-gate build-image smoke-stack smoke-stack-down

check:
	.venv/bin/ruff check backend tests/backend
	.venv/bin/python -m pytest tests/backend -q
	cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
	.venv/bin/python scripts/realtime_security_gate.py
	.venv/bin/voice-console fake-e2e

realtime-upgrade-gate:
	.venv/bin/python scripts/realtime_upgrade_gate.py --hermes-repo "$${HERMES_REALTIME_REPO:?set HERMES_REALTIME_REPO}"

browser-check:
	cd frontend && pnpm build && pnpm test:e2e

build-image:
	docker build -t hermes-voice-console:local .

smoke-stack:
	docker compose -f deploy/compose.example.yaml up --build --wait

smoke-stack-down:
	docker compose -f deploy/compose.example.yaml down --volumes --remove-orphans
