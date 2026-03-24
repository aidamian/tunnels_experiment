RUNTIME_ENV := servers/.runtime/dind.env
PERSISTENT_SERVICE_DATA_VOLUME := tunnels-experiment-persistent-service-data
COMPOSE := docker compose --project-directory servers -f servers/docker-compose.yml

.PHONY: prepare-runtime ensure-persistent-data config up down start continuous smoke reset-data

prepare-runtime:
	python3 servers/src/utils/prepare_runtime.py

ensure-persistent-data:
	@docker volume inspect $(PERSISTENT_SERVICE_DATA_VOLUME) >/dev/null 2>&1 || docker volume create $(PERSISTENT_SERVICE_DATA_VOLUME) >/dev/null

config: prepare-runtime
	$(COMPOSE) config -q

up: prepare-runtime ensure-persistent-data
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down --remove-orphans --volumes

start:
	./start_e2e.sh

continuous:
	./start_host.sh

smoke:
	@echo "usage: python3 clients/src/utils/smoke_test.py --run-ts <RUN_TS>"

reset-data:
	docker volume rm -f $(PERSISTENT_SERVICE_DATA_VOLUME)
