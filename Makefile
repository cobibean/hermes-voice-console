.PHONY: install-backend install-frontend test-backend test-frontend lint-frontend typecheck-frontend build-frontend fake-e2e test-all serve fake-target

install-backend:
	python -m venv .venv
	. .venv/bin/activate && pip install -e '.[dev]'

install-frontend:
	cd frontend && pnpm install

test-backend:
	. .venv/bin/activate && pytest tests/backend -q

lint-frontend:
	cd frontend && pnpm lint

typecheck-frontend:
	cd frontend && pnpm typecheck

test-frontend:
	cd frontend && pnpm test

build-frontend:
	cd frontend && pnpm build

fake-e2e:
	. .venv/bin/activate && voice-console fake-e2e

test-all: test-backend lint-frontend typecheck-frontend test-frontend build-frontend fake-e2e

serve:
	. .venv/bin/activate && voice-console serve --config config/voice.yaml --targets config/targets.yaml

fake-target:
	. .venv/bin/activate && voice-console fake-target --port 9876
