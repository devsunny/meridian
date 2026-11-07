# Meridian reference product — developer commands
# Windows users can run the underlying commands directly; see README.

UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
API := $(UV) run --project services/platform-api
WEB := apps/web

.PHONY: setup api worker scheduler web test test-fe lint build up down obs logs compose-check k8s-check

setup:
	$(UV) sync --project services/platform-api --extra dev
	cd $(WEB) && npm_config_cache=$(CURDIR)/.npm-cache npm ci

api:
	$(API) uvicorn meridian.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(API) python -m meridian.engine.worker

scheduler:
	$(API) python -m meridian.engine.scheduler

web:
	cd $(WEB) && npm run dev

test:
	$(API) pytest services/platform-api/tests -q -p no:cacheprovider

test-fe:
	cd $(WEB) && npm run lint

lint:
	$(API) ruff check services/platform-api/src packages/connector-sdk/src
	cd $(WEB) && npm run lint

build:
	cd $(WEB) && npm run build

up:
	docker compose -f deploy/compose/app.yaml up --build -d
	docker compose -f deploy/compose/app.yaml ps

obs:
	docker compose -f deploy/compose/app.yaml --profile obs up --build -d

down:
	docker compose -f deploy/compose/app.yaml down

logs:
	docker compose -f deploy/compose/app.yaml logs -f --tail=100

compose-check:
	docker compose -f deploy/compose/app.yaml config --quiet

k8s-check:
	kubectl kustomize deploy/k8s > /dev/null
