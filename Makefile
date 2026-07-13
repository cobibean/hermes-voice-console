.PHONY: check build-image smoke-stack smoke-stack-down

check:
	.venv/bin/ruff check backend tests/backend
	.venv/bin/python -m pytest tests/backend -q
	cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
	.venv/bin/voice-console fake-e2e

build-image:
	docker build -t hermes-voice-console:local .

smoke-stack:
	docker compose -f deploy/compose.example.yaml up --build --wait

smoke-stack-down:
	docker compose -f deploy/compose.example.yaml down --volumes --remove-orphans
