RUNTIME_ENV := .runtime/tunnels.env

.PHONY: prepare-runtime up down logs smoke config

prepare-runtime:
	python3 scripts/prepare_runtime.py

config: prepare-runtime
	docker compose config

up: prepare-runtime
	docker compose up --build -d

down:
	docker compose down --remove-orphans

logs:
	docker compose logs -f --tail=100

smoke: prepare-runtime
	python3 scripts/smoke_test.py
