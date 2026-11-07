# Local development shortcuts. Requires GNU make (Git Bash/WSL/macOS/Linux).
# On Windows PowerShell, run the underlying `docker compose` commands directly.

COMPOSE := docker compose -f docker-compose.yaml
OPA_IMAGE := openpolicyagent/opa:latest

.PHONY: help up core obs aws down reset ps logs policy-test policy-fmt validate seed

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: core ## Start the core stack and wait for health
	@$(COMPOSE) ps

core: ## Start core services
	$(COMPOSE) up -d postgres redis minio minio-init iceberg-rest trino temporal temporal-ui keycloak opa mailpit otel-collector

obs: ## Start observability (Prometheus + Grafana)
	$(COMPOSE) --profile obs up -d prometheus grafana

aws: ## Start LocalStack (Secrets Manager, SQS, KMS)
	$(COMPOSE) --profile aws up -d localstack

down: ## Stop everything, keep volumes
	$(COMPOSE) --profile obs --profile aws down

reset: ## Stop everything and delete volumes
	$(COMPOSE) --profile obs --profile aws down -v

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Tail logs for all services
	$(COMPOSE) logs -f --tail=100

policy-fmt: ## Format Rego policies
	docker run --rm -v "$(CURDIR)/../policies:/policies" $(OPA_IMAGE) fmt --write /policies

policy-test: ## Run Rego policy tests
	docker run --rm -v "$(CURDIR)/../policies:/policies" $(OPA_IMAGE) test /policies -v

validate: ## Validate YAML and compose config
	$(COMPOSE) config --quiet
	@echo "compose config OK"

seed: ## Load demo tenants, connections and datasets (requires services running from source)
	@echo "Run: python -m edp_seed --env local"
