# IMPLEMENTATION.md

## Role
This file is the source of truth for the current architecture, workflow, validation, and guardrails.

## Status

- Phase: verified two-host DinD topology with an app-side bridge-backed pgAdmin flow
- Latest verified combined host-and-app proof run: `260327_105603`
- Latest verified app-only proof run: `260327_105232`

## Objective

Build a reproducible demo showing that:

- `dind-host-server` runs origin services and their Cloudflare Tunnel connectors
- server startup can be limited to specific origin services with `ENABLED_SERVICES`
- `dind-host-app` can run a local Python bridge that talks to the public PostgreSQL tunnel hostname
- a child app container inside `dind-host-app` can connect to that bridge as if PostgreSQL were local
- `dind-host-app` can publish that app container over a separate HTTPS tunnel
- no top-level DinD host publishes service ports to the real machine
- the original real-machine Python client proof path still works

## Architecture

### Worlds

- `servers/`
  - owns the origin DinD host, server tunnel inventory, server runtime env, and server raw logs

- `apps/`
  - owns the app DinD host, app runtime env, and app raw logs

- `clients/`
  - owns the real-machine Python proof client, `clients/services.json`, client virtualenv inputs, and client raw logs

- `shared/`
  - is currently reserved for future neutral reusable code; the active bridge and logger live in the Ratio1 SDK instead of this repository

- root
  - owns orchestration scripts, tracked docs, and tracked markdown summaries only

### Separation Rules

- client code does not import from `servers/` or `apps/`
- app code does not import from `servers/` or `clients/`
- server code does not import from `clients/` or `apps/`
- client and app code may import from `shared/` only when the shared module is world-neutral and does not read world-owned runtime files or secrets
- client code does not read `servers/.runtime/`, `servers/_logs/raw/`, `apps/.runtime/`, or `apps/_logs/raw/`
- app code does not read `servers/tunnels.json`, `servers/_logs/raw/`, or `clients/services.json`
- server code does not read `clients/services.json`, `clients/_logs/raw/`, `apps/.runtime/`, or `apps/_logs/raw/`
- shared code must not read `servers/tunnels.json`, any world-owned runtime directory, or any world-owned raw-log directory
- root scripts may coordinate worlds by passing CLI arguments or environment values, but they must not create a shared runtime directory at repo root

### Topology

- top-level Compose services:
  - `dind-host-server`
  - `dind-host-app`

- direct child containers started by `dind-host-server`:
  - `neo4j-demo` when `ENABLED_SERVICES` includes `neo4j`
  - `postgres-demo` when `ENABLED_SERVICES` includes `pgsql`

- direct child containers started by `dind-host-app`:
  - `pgadmin-demo`

- real-machine client:
  - `clients/src/experiment_runner.py`

### Tunnel Assignment

- tunnel 1 -> Neo4j HTTPS
- tunnel 2 -> Neo4j Bolt/TCP
- tunnel 3 -> PostgreSQL TCP
- tunnel 4 -> app HTTPS UI

### Transport Model

- `cloudflared tunnel run --url http://127.0.0.1:17474` publishes Neo4j HTTP in normal HTTP proxy mode
- `cloudflared tunnel run --url tcp://127.0.0.1:17687` publishes Neo4j Bolt in Cloudflare TCP mode
- `cloudflared tunnel run --url tcp://127.0.0.1:15432` publishes PostgreSQL in Cloudflare TCP mode
- `cloudflared tunnel run --url http://127.0.0.1:18080` publishes the app UI in normal HTTP proxy mode
- published Tunnel TCP applications still require a TCP-to-WebSocket bridge on the consumer side
- host-side bridge code imports `UniversalBridgeServer` from `ratio1.bridge`
- `dind-host-app` launches its bridge with the SDK `r1bridge` CLI
- `pgadmin-demo` uses `--network host` inside `dind-host-app`, so `127.0.0.1:55432` refers to the bridge in the app DinD host, not the real machine

### Runtime Generation

- server runtime generation:
  - `python3 servers/src/utils/prepare_runtime.py [--enabled-services ...]`
  - writes `servers/.runtime/dind.env`
  - derives public hosts and tunnel tokens for all four tunnel roles

- app runtime generation:
  - `python3 apps/src/utils/prepare_runtime.py ...`
  - writes `apps/.runtime/dind.env`
  - is driven by root orchestration after server runtime generation
  - receives only the derived values needed by `dind-host-app`

### Client Contract

`clients/services.json` remains the only client-owned service inventory.

It defines:

- stable service keys
- public hostnames or URLs
- which client-visible services require local bridges
- default client-side local bridge ports
- operator-facing bridge purpose text

### Runtime Artifacts

- server runtime:
  - `servers/.runtime/dind.env`
  - `servers/_logs/raw/*`

- app runtime:
  - `apps/.runtime/dind.env`
  - `apps/_logs/raw/*`

- client runtime:
  - `clients/services.json`
  - `clients/.venv/`
  - `clients/_logs/raw/*`

- repo-level docs:
  - `_logs/RUNLOG.md`
  - `_logs/*_summary.md`

## Operating Rules

- keep source tunnel secrets only in `servers/tunnels.json`
- treat `servers/.runtime/` and `apps/.runtime/` as ignored derived runtime state
- keep runtime output under each world’s own `_logs/raw/`
- keep root `_logs/` markdown-only
- do not publish any service port from `dind-host-server` or `dind-host-app` to the real machine
- do not run `cloudflared tunnel run` anywhere except `dind-host-server` and `dind-host-app`
- do not move the active proof client back into a container
- do not pretend PostgreSQL or Bolt are HTTP services
- do not change the tunnel-role mapping without intentionally updating this document

## Logging Rules

- root entrypoint scripts use ANSI-colored step logs
- Python status logs use quiet `ratio1.Logger` instances instead of repo-owned ANSI helper modules
- server shell logs use scope-based ANSI colors in `servers/_logs/raw/*.log`
- app shell and bridge logs use scope-based ANSI colors in `apps/_logs/raw/*.log`
- client bridge log files are written by Ratio1 logger instances under `clients/_logs/raw/<RUN_TS>/_logs/*.txt`
- JSON, Markdown, and env files must remain plain text
- scripts whose stdout is parsed as JSON keep that stdout plain and do not route it through the SDK logger

## Expected Workflow

### Host-side Proof Path

1. `python3 servers/src/utils/prepare_runtime.py --enabled-services neo4j,pgsql`
2. derive `RUN_TS`, PostgreSQL public host, and app UI tunnel values from `servers/.runtime/dind.env`
3. `python3 apps/src/utils/prepare_runtime.py ...`
4. `docker volume create tunnels-experiment-persistent-service-data || true`
5. `docker compose --project-directory servers -f servers/docker-compose.yml up --build -d`
6. `python3 servers/src/utils/wait_for_stack.py --run-ts <RUN_TS>`
7. `clients/.venv/bin/python clients/src/experiment_runner.py --run-ts <RUN_TS>`
8. `python3 clients/src/utils/smoke_test.py --run-ts <RUN_TS>`
9. `docker compose --project-directory apps -f apps/docker-compose.yml up --build -d`
10. `python3 apps/src/utils/wait_for_stack.py --run-ts <RUN_TS>`
11. `python3 apps/src/utils/verify_public_ui.py --run-ts <RUN_TS> --timeout-seconds 60`
12. `python3 clients/src/utils/append_runlog.py --run-ts <RUN_TS>`
13. `python3 clients/src/utils/write_summary.py --run-ts <RUN_TS>`
14. tear down both Compose projects unless `--keep-up` was requested

Default host-side automation:

- `./start_e2e.sh --duration-seconds 1`

Manual host bridge path:

- `timeout -s INT 120 ./start_host.sh --verify`

### App-side Consumer Path

1. `python3 servers/src/utils/prepare_runtime.py --enabled-services pgsql`
2. derive `RUN_TS`, PostgreSQL public host, and app UI tunnel values from `servers/.runtime/dind.env`
3. `python3 apps/src/utils/prepare_runtime.py ...`
4. `docker compose --project-directory servers -f servers/docker-compose.yml up --build -d`
5. `python3 servers/src/utils/wait_for_stack.py --run-ts <RUN_TS>`
6. `docker compose --project-directory apps -f apps/docker-compose.yml up --build -d`
7. `python3 apps/src/utils/wait_for_stack.py --run-ts <RUN_TS>`
8. `python3 apps/src/utils/verify_public_ui.py --run-ts <RUN_TS> --timeout-seconds 10`
9. keep both Compose projects running until Ctrl-C, then tear them down unless `--keep-up` was requested

Default app-side automation:

- `./start_apps.sh`

## Validation Discipline

- static checks:
  - `bash -n start_e2e.sh start_host.sh start_apps.sh`
  - `python3 -m compileall clients/src servers/src apps/src`
  - `docker compose --project-directory servers -f servers/docker-compose.yml config -q`
  - `docker compose --project-directory apps -f apps/docker-compose.yml config -q` after app runtime generation

- host-side functional proof:
  - `./start_e2e.sh --duration-seconds 1`

- app-side functional proof:
  - `timeout -s INT 120 ./start_apps.sh`
  - `python3 apps/src/utils/verify_public_ui.py --run-ts <RUN_TS> --timeout-seconds 10`
  - `docker inspect dind-host-server --format '{{json .NetworkSettings.Ports}}'`
  - `docker inspect dind-host-app --format '{{json .NetworkSettings.Ports}}'`

## Definition Of Done

- `python3 servers/src/utils/prepare_runtime.py` succeeds against `servers/tunnels.json`
- `python3 apps/src/utils/prepare_runtime.py` succeeds when given the derived server values
- `./start_e2e.sh --duration-seconds 1` still proves:
  - Neo4j over public HTTPS
  - Neo4j Bolt through the client-side local bridge
  - PostgreSQL through the client-side local bridge
  - the pgAdmin app flow over the app-host bridge and tunnel 4
- `./start_apps.sh` proves:
  - `dind-host-server` can start only `pgsql`
  - `dind-host-app` can connect to the public PostgreSQL tunnel through its local Python bridge
  - `pgadmin-demo` can reach PostgreSQL through that bridge
  - the public app UI responds over tunnel 4 while the script remains active until Ctrl-C
- `docker inspect dind-host-server --format '{{json .NetworkSettings.Ports}}'` shows only null bindings
- `docker inspect dind-host-app --format '{{json .NetworkSettings.Ports}}'` shows only null bindings
- server runtime artifacts stay under `servers/`
- app runtime artifacts stay under `apps/`
- client runtime artifacts stay under `clients/`
- repo-level markdown logs stay under root `_logs/`
- this file and the latest root `_logs/*_summary.md` match the verified state

## Critic Checklist

### Secrets

- no tunnel token appears in tracked markdown or tracked config
- `servers/tunnels.json` remains ignored
- `servers/.runtime/` remains ignored
- `apps/.runtime/` remains ignored

### Separation

- no client file reads server or app runtime/log folders
- no app file reads `servers/tunnels.json` or client-owned runtime files
- no server file reads client or app runtime files
- no repo-owned bridge implementation remains on the hot path; TCP bridge behavior comes from `ratio1.bridge`
- the server DinD image build context stays under `servers/`
- the app DinD image build context stays under `apps/`

### Topology

- Compose defines exactly two top-level services overall:
  - `dind-host-server`
  - `dind-host-app`
- neither top-level service publishes ports to the real machine
- `cloudflared tunnel run` exists only inside the two top-level DinD hosts
- server service selection is driven by `ENABLED_SERVICES`
- `pgadmin-demo` reaches PostgreSQL through the app-host bridge, not through direct network sharing between the two DinD hosts

### Functional Proof

- the latest host-side generated report shows `all_ok: true`
- the latest app-side topology marker shows:
  - `postgres_bridge`
  - `pgadmin_http`
  - `app_ui_https`
- the latest public app UI verification returns success

### Operational Quality

- `bash -n start_e2e.sh start_host.sh start_apps.sh` passes
- `python3 -m compileall clients/src servers/src apps/src` passes
- `./start_e2e.sh --duration-seconds 1` passes and records the app proof in `_logs/260327_105603_summary.md`
- `./start_apps.sh --exit-after-verify` passes for run `260327_105232`
