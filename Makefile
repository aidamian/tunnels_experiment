RUNTIME_ENV := .runtime/dind.env

.PHONY: prepare-runtime config up down start continuous smoke

prepare-runtime:
	python3 src/utils/prepare_runtime.py

config: prepare-runtime
	docker compose config -q

up: prepare-runtime
	docker compose up --build -d

down:
	docker compose down --remove-orphans --volumes

start:
	./start_e2e.sh

continuous:
	./start_host.sh

smoke:
	@echo "usage: python3 src/utils/smoke_test.py --run-ts <RUN_TS>"
