# IMPLEMENTATION.md

## Role
This file is the single source of truth for architecture, operating rules, validation, and script ownership.

## Status
- Phase: verified working demo
- Current objective: keep the topology simple, lean, and reproducible while preserving sound separation of concerns

## Objective
Build a reproducible demo showing that:
- a single top-level Docker-in-Docker host container can run all outbound Cloudflare Tunnel processes;
- Neo4j and PostgreSQL can each run as direct child containers of that DinD host;
- no service port is published from the top-level DinD host container to the real machine;
- a Python script running directly on the real machine can behave like external clients and reach those services only through the public tunnel hostnames.

## Architecture
### Topology
- Top-level Compose service:
  - `dind-host-container`
- Direct child containers started by `dind-host-container`:
  - `neo4j-demo`
  - `postgres-demo`
- Host-side consumer:
  - `src/experiment_runner.py`

### Tunnel assignment
- tunnel 1 -> Neo4j HTTPS
- tunnel 2 -> Neo4j Bolt/TCP
- tunnel 3 -> PostgreSQL TCP
- tunnel 4 -> reserved and unused by the automated experiment

### Transport model
- `cloudflared tunnel run --url http://127.0.0.1:17474` publishes Neo4j HTTP in standard HTTP proxy mode.
- `cloudflared tunnel run --url tcp://127.0.0.1:17687` and `tcp://127.0.0.1:15432` publish Bolt and PostgreSQL in Cloudflare TCP mode.
- In that TCP mode, the public hostname is not a native raw database socket.
- The client side therefore needs a TCP-to-WebSocket bridge.
- This repository uses its own Python bridge, not client-side `cloudflared`.

### Runtime files
- `.runtime/dind.env`
  - DinD-only runtime file
  - contains `RUN_TS`, demo credentials, public hostnames, and tunnel tokens
- `.runtime/public_hosts.json`
  - host-side runtime file
  - contains only the public FQDNs needed by host-side clients and bridges

## Operating Rules
- Keep tunnel secrets only in `tunnels.json` and generated `.runtime/` files.
- Treat `.runtime/` as disposable runtime state.
- Treat `_logs/raw/` as disposable runtime output.
- Append `_logs/RUNLOG.md` only after a full end-to-end run.
- Keep `_logs/*_summary.md` tracked and `_logs/*.log` untracked.
- Do not publish any service port from the top-level DinD host container to the real machine.
- Do not run `cloudflared tunnel run` anywhere except the top-level DinD host container.
- Do not move the active Python consumer back into a container.
- Do not pretend PostgreSQL or Bolt are HTTP services.
- Do not reintroduce extra DinD child containers unless this file is intentionally updated first.

## Expected Workflow
1. `python3 src/utils/prepare_runtime.py`
2. `docker compose up --build -d`
3. `python3 src/utils/wait_for_stack.py --run-ts <RUN_TS>`
4. `.venv/bin/python src/experiment_runner.py --run-ts <RUN_TS>`
5. `python3 src/utils/smoke_test.py --run-ts <RUN_TS>`
6. `python3 src/utils/append_runlog.py --run-ts <RUN_TS>`
7. `python3 src/utils/write_summary.py --run-ts <RUN_TS>`
8. `docker compose down --remove-orphans --volumes`

The default one-command end-to-end path is:
- `./start_e2e.sh`

The optional manual local-bridge path is:
- `.venv/bin/python src/utils/start_local_bridges.py`

The operator-focused host-testing path is:
- `./start_host.sh`

## Validation Discipline
- Run `python3 src/utils/prepare_runtime.py` before Compose commands.
- Use `docker compose config -q` to validate Compose without printing secret-expanded config.
- Use `./start_e2e.sh` for the normal integration path.
- Use `python3 src/utils/smoke_test.py --run-ts ...` for report validation when debugging.

## Definition Of Done
- `python3 src/utils/prepare_runtime.py` succeeds against the local `tunnels.json`.
- `docker compose up --build -d` brings up only `dind-host-container`.
- `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'` shows no host bindings.
- Neo4j HTTPS works through tunnel 1.
- Neo4j Bolt works through tunnel 2 via a host-side local TCP bridge.
- PostgreSQL works through tunnel 3 via a host-side local TCP bridge.
- The host-side experiment writes and reads timestamped proof records in both databases.
- `_logs/raw/` contains run-specific artifacts.
- `_logs/RUNLOG.md` contains the end-to-end result.
- The current timestamped `_logs/*_summary.md` matches the verified run.

## Critic Checklist
### Secrets
- No tunnel token appears in tracked files, markdown summaries, or user-facing command summaries.
- `.runtime/` remains ignored.
- `_logs/raw/` contains runtime output only.

### Topology
- Compose defines exactly one top-level service: `dind-host-container`.
- `dind-host-container` publishes no ports to the real machine.
- The DinD image contains tracked startup scripts instead of relying on bind-mounted entry scripts.
- Neo4j runs inside `neo4j-demo` as a direct child container of the DinD host.
- PostgreSQL runs inside `postgres-demo` as a direct child container of the DinD host.
- `cloudflared tunnel run` exists only inside `dind-host-container`.
- The active Python experiment runs directly on the real machine.

### Functional proof
- Neo4j HTTPS is verified over the public hostname.
- Neo4j Bolt is verified through the host-side local TCP bridge and a real driver query.
- PostgreSQL is verified through the host-side local TCP bridge and a real SQL query.
- The PostgreSQL proof inserts new timestamped rows and reads them back.
- The Neo4j proof creates new timestamped graph data and reads it back.
- The latest generated report shows `all_ok: true`.

### Operational quality
- `docker compose config -q` passes.
- `./start_e2e.sh` can drive the full run.
- `_logs/raw/` contains separated runtime artifacts.
- `_logs/RUNLOG.md` contains an end-to-end entry for the verified run.
- `README.md` and this file match the actual verified topology.

## Script Inventory
Labels used below:
- `Keep`: worth keeping as a separate script in the lean design.
- `Mergeable`: behavior is needed, but this separate file is not strictly necessary.
- `Optional`: not required for the core experiment.

### Shell scripts
- `start_e2e.sh`
  - purpose: one-command runner for the full automated experiment from runtime prep through teardown and logging.
  - reason: keeps the verified end-to-end path explicit and reproducible.
  - status: `Keep`

- `start_host.sh`
  - purpose: starts the DinD stack, waits for readiness, and runs the foreground Python bridge until `Ctrl+C`.
  - reason: supports direct host-side testing with tools such as DBeaver without also running the proof workload.
  - status: `Keep`

- `docker/dind/entrypoint.sh`
  - purpose: starts `dockerd` inside `dind-host-container` and hands off to the orchestrator.
  - reason: keeps container bootstrap separate from service orchestration.
  - status: `Keep`

- `docker/dind/orchestrator.sh`
  - purpose: discovers service scripts, starts them, waits for ready markers, and writes the aggregated topology file.
  - reason: allows the DinD host to stay service-agnostic.
  - status: `Mergeable`

- `docker/dind/lib/common.sh`
  - purpose: shared logging, readiness, file-path, and tunnel-launch helpers for DinD shell scripts.
  - reason: removes duplicated shell plumbing.
  - status: `Mergeable`

- `docker/dind/servers/neo4j.sh`
  - purpose: starts the Neo4j child container, waits for Cypher readiness, seeds minimal data, and starts the Neo4j HTTP and Bolt tunnels.
  - reason: keeps all Neo4j-specific behavior in one place.
  - status: `Mergeable`

- `docker/dind/servers/pgsql.sh`
  - purpose: starts the PostgreSQL child container, creates the proof table, and starts the PostgreSQL tunnel.
  - reason: keeps all PostgreSQL-specific behavior in one place.
  - status: `Mergeable`

### Core Python scripts
- `src/experiment_runner.py`
  - purpose: main host-side proof runner; starts local bridges, runs all proof cycles, and writes the machine-readable report.
  - reason: central coordinator for the real experiment.
  - status: `Keep`

- `src/bridge/universal.py`
  - purpose: reusable TCP-to-WebSocket bridge used for Cloudflare-published TCP services.
  - reason: isolates the transport conversion from the proof logic.
  - status: `Keep`

- `src/simulators/postgres.py`
  - purpose: PostgreSQL write/read proof cycle.
  - reason: keeps PostgreSQL-specific proof logic out of the coordinator.
  - status: `Mergeable`

- `src/simulators/neo4j_bolt.py`
  - purpose: Neo4j Bolt write/read proof cycle.
  - reason: keeps Bolt-specific proof logic out of the coordinator.
  - status: `Mergeable`

- `src/simulators/neo4j_https.py`
  - purpose: Neo4j HTTPS read proof cycle.
  - reason: keeps HTTP-specific proof logic out of the coordinator.
  - status: `Mergeable`

### Runtime and verification helpers
- `src/utils/prepare_runtime.py`
  - purpose: turns `tunnels.json` into `.runtime/dind.env` for the DinD host and `.runtime/public_hosts.json` for host-side clients.
  - reason: separates server-side tunnel secrets from the host-side client view.
  - status: `Keep`

- `src/utils/wait_for_stack.py`
  - purpose: waits until the DinD host publishes the topology-ready marker.
  - reason: separates readiness polling from the shell entrypoints.
  - status: `Mergeable`

- `src/utils/smoke_test.py`
  - purpose: validates that the generated report proves all required paths.
  - reason: provides a disciplined post-run check.
  - status: `Optional`

- `src/utils/append_runlog.py`
  - purpose: appends a compact markdown entry to `_logs/RUNLOG.md`.
  - reason: keeps long-term run history readable.
  - status: `Optional`

- `src/utils/write_summary.py`
  - purpose: writes the tracked per-run summary markdown file.
  - reason: keeps a short verified snapshot for each important run.
  - status: `Optional`

### Manual bridge helpers
- `src/utils/start_local_bridges.py`
  - purpose: manual CLI that exposes local PostgreSQL and Neo4j Bolt ports for DBeaver and Bolt consumers.
  - reason: supports the non-automated manual client workflow without client-side `cloudflared`.
  - status: `Optional`

- `src/utils/local_bridges.py`
  - purpose: shared bridge specs, runtime loading, and verification helpers for the manual bridge CLI.
  - reason: keeps `start_local_bridges.py` focused on CLI behavior.
  - status: `Optional`

### Small shared helpers
- `src/utils/demo_config.py`
  - purpose: centralizes non-secret demo constants such as database credentials, local bridge ports, and default timings.
  - reason: lets host-side code avoid reading the DinD runtime env.
  - status: `Mergeable`

- `src/utils/dependencies.py`
  - purpose: lazy imports for `requests`, `neo4j`, `psycopg`, and `websocket-client`.
  - reason: allows lightweight CLI paths such as `--help` to work without eager imports.
  - status: `Mergeable`

- `src/utils/docker_runtime.py`
  - purpose: reads top-level Docker status and published-port bindings.
  - reason: centralizes Docker interrogation logic.
  - status: `Mergeable`

- `src/utils/envfiles.py`
  - purpose: parses the generated host-side runtime file `.runtime/public_hosts.json`.
  - reason: keeps public-host loading consistent across host-side bridge consumers.
  - status: `Mergeable`

- `src/utils/files.py`
  - purpose: atomic JSON file writing helper.
  - reason: avoids partial report writes.
  - status: `Mergeable`

- `src/utils/topology.py`
  - purpose: loads the topology snapshot produced by the DinD orchestrator, with a fallback.
  - reason: keeps reporting resilient even if the snapshot is absent or malformed.
  - status: `Mergeable`

## Simplification Guidance
If the repository should become leaner while preserving good separation of concerns, the next safe reductions are:
- merge `docker/dind/orchestrator.sh` and `docker/dind/lib/common.sh` if dynamic service discovery does not need to stay generic;
- merge the three simulator modules into `src/experiment_runner.py` if a single-file host proof runner is preferred over per-protocol separation;
- merge `envfiles.py`, `files.py`, `docker_runtime.py`, `dependencies.py`, and `topology.py` into one compact runtime helper module;
- keep `start_local_bridges.py` only if the manual DBeaver/Bolt workflow remains a supported feature;
- drop `append_runlog.py`, `write_summary.py`, and possibly `smoke_test.py` if strict tracked run history is no longer required.

## Verified State
- Verified automated run identifier: `260320_210435`
- Verified continuous host-testing run identifier: `260320_210613`
- Verified outcome:
  - `./start_e2e.sh --duration-seconds 1` completed end to end and then stopped the stack automatically;
  - `./start_host.sh --verify` reached the foreground Python bridge and printed manual client settings before the interrupt-driven shutdown path was exercised;
  - the live bridge verification inside run `260320_210613` returned PostgreSQL `SELECT 1` -> `1`;
  - the live bridge verification inside run `260320_210613` returned Neo4j Bolt `RETURN 1` -> `1`;
  - `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'` showed no host bindings;
  - Neo4j HTTPS succeeded over `c74d8a4e03e6.ratio1.link`;
  - Neo4j Bolt succeeded through the host-side local bridge on `127.0.0.1:17687`;
  - PostgreSQL succeeded through the host-side local bridge on `127.0.0.1:15432`;
  - the host-side experiment completed three proof cycles.
