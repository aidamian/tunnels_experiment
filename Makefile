RUNTIME_ENV := .runtime/dind.env
PERSISTENT_SERVICE_DATA_VOLUME := tunnels-experiment-persistent-service-data

.PHONY: prepare-runtime ensure-persistent-data config up down start continuous smoke reset-data

prepare-runtime:
	python3 src/utils/prepare_runtime.py

ensure-persistent-data:
	@docker volume inspect $(PERSISTENT_SERVICE_DATA_VOLUME) >/dev/null 2>&1 || docker volume create $(PERSISTENT_SERVICE_DATA_VOLUME) >/dev/null

config: prepare-runtime
	docker compose config -q

up: prepare-runtime ensure-persistent-data
	docker compose up --build -d

down:
	docker compose down --remove-orphans --volumes

start:
	./start_e2e.sh

continuous:
	./start_host.sh

smoke:
	@echo "usage: python3 src/utils/smoke_test.py --run-ts <RUN_TS>"

reset-data:
	docker volume rm -f $(PERSISTENT_SERVICE_DATA_VOLUME)
