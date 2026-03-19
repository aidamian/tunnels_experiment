RUNTIME_ENV := .runtime/tunnels.env

.PHONY: prepare-runtime config up down start smoke

prepare-runtime:
	python3 scripts/prepare_runtime.py

config: prepare-runtime
	docker compose config -q

up: prepare-runtime
	docker compose up --build -d

down:
	docker compose down --remove-orphans --volumes

start:
	./start.sh

smoke:
	python3 scripts/smoke_test.py
