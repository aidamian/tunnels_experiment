# IMPLEMENTATION.md

## Role
This file is the source of truth for architecture, workflow, validation, and operational guardrails.

## Status

- Phase: verified working demo after the client/server separation refactor
- Current objective: keep the topology reproducible while enforcing strict separation of concerns

## Objective

Build a reproducible demo showing that:

- one top-level Docker-in-Docker host container runs all outbound Cloudflare Tunnel connectors
- Neo4j and PostgreSQL run as direct child containers of that DinD host
- no service port is published from the top-level DinD host container to the real machine
- a Python client running directly on the real machine reaches those services only through the public hostnames and host-side local TCP bridges

## Architecture

### Worlds

- `servers/`
  - `docker-compose.yml`
  - `docker/dind/`
  - `tunnels.json`
  - `.runtime/dind.env`
  - `_logs/raw/`

- `clients/`
  - `services.json`
  - `requirements.txt`
  - `src/`
  - `.venv/`
  - `_logs/raw/`

- root
  - `start_e2e.sh`
  - `start_host.sh`
  - `Makefile`
  - `_logs/`
    - tracked markdown docs only

### Separation Rules

- client code does not import from `servers/`
- server code does not import from `clients/`
- client code does not read `servers/.runtime/` or `servers/_logs/raw/`
- server code does not read `clients/services.json` or `clients/_logs/raw/`
- root scripts may coordinate both worlds, but they must not create a new shared runtime folder at repo root

### Topology

- top-level Compose service:
  - `dind-host-container`

- direct child containers started by `dind-host-container`:
  - `neo4j-demo`
  - `postgres-demo`

- host-side client:
  - `clients/src/experiment_runner.py`

### Tunnel Assignment

- tunnel 1 -> Neo4j HTTPS
- tunnel 2 -> Neo4j Bolt/TCP
- tunnel 3 -> PostgreSQL TCP
- tunnel 4 -> reserved and unused by the automated experiment

### Transport Model

- `cloudflared tunnel run --url http://127.0.0.1:17474` publishes Neo4j HTTP in normal HTTP proxy mode
- `cloudflared tunnel run --url tcp://127.0.0.1:17687` publishes Neo4j Bolt in Cloudflare TCP mode
- `cloudflared tunnel run --url tcp://127.0.0.1:15432` publishes PostgreSQL in Cloudflare TCP mode
- published Tunnel TCP applications still require a client-side TCP-to-WebSocket bridge
- this repository implements that bridge in Python under `clients/src/bridge/universal.py`

### Client Contract

`clients/services.json` is the only client-owned service inventory.

It defines:

- public hostname or URL
- service key
- service type
- bridge defaults for TCP-backed services
- operator-facing bridge purpose text

The manual bridge CLI and automated experiment both source bridge targets and default local ports from this file.

### Runtime Artifacts

- server runtime:
  - `servers/.runtime/dind.env`
  - `servers/_logs/raw/*`

- client runtime:
  - `clients/services.json`
  - `clients/.venv/`
  - `clients/_logs/raw/*`

- repo-level docs:
  - `_logs/RUNLOG.md`
  - `_logs/*_summary.md`

## Operating Rules

- keep tunnel secrets only in `servers/tunnels.json` and `servers/.runtime/dind.env`
- treat `servers/.runtime/` as disposable server runtime state
- treat `servers/_logs/raw/` and `clients/_logs/raw/` as disposable runtime output
- keep `_logs/*_summary.md` tracked and `_logs/RUNLOG.md` tracked
- do not publish any service port from the top-level DinD host container to the real machine
- do not run `cloudflared tunnel run` anywhere except the top-level DinD host container
- do not move the active Python client back into a container
- do not let client code read server-generated runtime or topology files
- do not let server code depend on client config files
- do not pretend PostgreSQL or Bolt are HTTP services
- do not change the tunnel-role mapping without intentionally updating this document

## Logging Rules

- root entrypoint scripts use ANSI-colored step logs
- server shell logs use scope-based ANSI colors in `servers/_logs/raw/*.log`
- client bridge logs use ANSI-colored `.log` streams in `clients/_logs/raw/*.log`
- JSON reports, Markdown summaries, and env files must remain plain text

## Expected Workflow

1. `python3 servers/src/utils/prepare_runtime.py`
2. `docker volume create tunnels-experiment-persistent-service-data || true`
3. `docker compose --project-directory servers -f servers/docker-compose.yml up --build -d`
4. `python3 servers/src/utils/wait_for_stack.py --run-ts <RUN_TS>`
5. `clients/.venv/bin/python clients/src/experiment_runner.py --run-ts <RUN_TS>`
6. `python3 clients/src/utils/smoke_test.py --run-ts <RUN_TS>`
7. `python3 clients/src/utils/append_runlog.py --run-ts <RUN_TS>`
8. `python3 clients/src/utils/write_summary.py --run-ts <RUN_TS>`
9. `docker compose --project-directory servers -f servers/docker-compose.yml down --remove-orphans --volumes`

Default end-to-end path:

- `./start_e2e.sh`

Manual bridge path:

- `./start_host.sh --verify`
- `clients/.venv/bin/python clients/src/bridge/start_local_bridges.py --verify`

## Validation Discipline

- run `python3 servers/src/utils/prepare_runtime.py` before Compose commands
- use `docker compose --project-directory servers -f servers/docker-compose.yml config -q`
- use `./start_e2e.sh --duration-seconds 1` for the normal integration path
- use `timeout -s INT 120 ./start_host.sh --verify` for the manual bridge path
- use `python3 clients/src/utils/smoke_test.py --run-ts ...` for report validation

## Definition Of Done

- `python3 servers/src/utils/prepare_runtime.py` succeeds against `servers/tunnels.json`
- `docker compose --project-directory servers -f servers/docker-compose.yml up --build -d` brings up only `dind-host-container`
- `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'` shows no host bindings
- Neo4j HTTPS works through the public hostname
- Neo4j Bolt works through the client-side local bridge defined by `clients/services.json`
- PostgreSQL works through the client-side local bridge defined by `clients/services.json`
- the host-side experiment writes and reads timestamped proof records in both databases
- server runtime artifacts stay under `servers/`
- client runtime artifacts stay under `clients/`
- repo-level markdown logs stay under root `_logs/`
- this file and the latest root `_logs/*_summary.md` match the verified state

## Critic Checklist

### Secrets

- no tunnel token appears in tracked markdown or tracked config
- `servers/tunnels.json` remains ignored
- `servers/.runtime/` remains ignored

### Separation

- no client file reads `servers/.runtime/`
- no client file reads `servers/_logs/raw/`
- no server file reads `clients/services.json`
- no server file reads `clients/_logs/raw/`
- the DinD image build context stays under `servers/`

### Topology

- Compose defines exactly one top-level service: `dind-host-container`
- `dind-host-container` publishes no ports to the real machine
- Neo4j runs inside `neo4j-demo` as a direct child container of the DinD host
- PostgreSQL runs inside `postgres-demo` as a direct child container of the DinD host
- `cloudflared tunnel run` exists only inside `dind-host-container`
- the active Python client runs directly on the real machine

### Functional Proof

- Neo4j HTTPS is verified over the public hostname
- Neo4j Bolt is verified through the local bridge and a real driver query
- PostgreSQL is verified through the local bridge and a real SQL query
- the latest generated report shows `all_ok: true`

### Operational Quality

- `bash -n start_e2e.sh start_host.sh` passes
- `python3 -m compileall clients/src servers/src` passes
- `docker compose --project-directory servers -f servers/docker-compose.yml config -q` passes
- `./start_e2e.sh --duration-seconds 1` passes
- `timeout -s INT 120 ./start_host.sh --verify` proves the manual bridge workflow

## Script Inventory

- `start_e2e.sh`
  - purpose: full automated end-to-end workflow
  - status: Keep

- `start_host.sh`
  - purpose: start the stack and hold the manual bridges in the foreground
  - status: Keep

- `servers/src/utils/prepare_runtime.py`
  - purpose: generate `servers/.runtime/dind.env`
  - status: Keep

- `servers/src/utils/wait_for_stack.py`
  - purpose: wait for the DinD topology-ready marker
  - status: Keep

- `clients/src/experiment_runner.py`
  - purpose: run the host-side proof workload
  - status: Keep

- `clients/src/bridge/universal.py`
  - purpose: reusable TCP-to-WebSocket bridge
  - status: Keep

- `clients/src/bridge/start_local_bridges.py`
  - purpose: manual bridge CLI driven by `clients/services.json`
  - status: Keep

- `clients/src/simulators/postgres.py`
  - purpose: PostgreSQL proof and manual verification
  - status: Keep

- `clients/src/simulators/neo4j_bolt.py`
  - purpose: Neo4j Bolt proof and manual verification
  - status: Keep

- `clients/src/simulators/neo4j_https.py`
  - purpose: Neo4j HTTPS proof
  - status: Keep
