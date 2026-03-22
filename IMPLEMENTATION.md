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

### Protocol invariants
- A native PostgreSQL, Bolt, or other TCP client requires a native TCP edge if the goal is truly no-bridge.
- HTTP/HTTPS and native database protocols are not interchangeable.
- Cloudflare Tunnel published TCP applications expose TCP over a WebSocket-based client path, not a native public TCP socket.
- Therefore the current published Tunnel TCP hostnames cannot satisfy a strict no-helper FQDN requirement for PostgreSQL or Bolt.

### No-bridge research snapshot
- Strict requirement:
  - client uses only FQDN plus native protocol
  - no local Python bridge
  - no client-side `cloudflared`
  - no WARP client
- Current repo state:
  - Neo4j HTTPS already satisfies the direct-FQDN requirement because it is HTTP-native.
  - Neo4j Bolt and PostgreSQL do not satisfy it because the current Tunnel TCP model requires a client-side transport adapter.
- Cloudflare-native paths:
  - Tunnel published applications:
    - works directly for HTTP/HTTPS
    - does not provide a native public TCP socket for PostgreSQL or Bolt
  - Tunnel private networking with private hostnames:
    - removes the Python bridge
    - still requires WARP or another Cloudflare One on-ramp, so it is not a strict no-helper solution
  - Spectrum:
    - is the Cloudflare product family that provides native public TCP/UDP edges
    - should be treated as the real Cloudflare analogue for ngrok-style TCP/UDP exposure
    - requires a topology change away from the current published-Tunnel-TCP assumption

### Short no-bridge plan
1. Stop trying to make published Tunnel TCP hostnames behave like native PostgreSQL or Bolt sockets. They do not.
2. Decide whether client software is acceptable:
   - if yes, evaluate private hostname routing with WARP and remove the local Python bridge
   - if no, move the TCP/UDP public edge to Spectrum instead of Tunnel
3. Treat Spectrum migration as an architecture change, not a small patch:
   - public edge becomes native TCP/UDP
   - backend connectivity must use a Spectrum-compatible origin path, not the current Tunnel TCP published app model
4. Keep HTTP facades application-specific only:
   - PostgREST, Hyperdrive-backed APIs, pgAdmin, or custom HTTPS layers may be useful for web access
   - they are not universal replacements for native PostgreSQL clients such as DBeaver

### Runtime files
- `.runtime/dind.env`
  - DinD-only runtime file
  - contains `RUN_TS`, demo credentials, public hostnames, and tunnel tokens
- `.runtime/public_hosts.json`
  - host-side runtime file
  - contains only the public FQDNs needed by host-side clients and bridges
- `tunnels-experiment-persistent-service-data`
  - external Docker volume mounted into `dind-host-container` at `/persistent-service-data`
  - stores child Neo4j and PostgreSQL data directories across full stack teardown

## Operating Rules
- Keep tunnel secrets only in `tunnels.json` and generated `.runtime/` files.
- Treat `.runtime/` as disposable runtime state.
- Treat `_logs/raw/` as disposable runtime output.
- Treat `tunnels-experiment-persistent-service-data` as durable database state.
- Append `_logs/RUNLOG.md` only after a full end-to-end run.
- Keep `_logs/*_summary.md` tracked and `_logs/*.log` untracked.
- Do not publish any service port from the top-level DinD host container to the real machine.
- Do not run `cloudflared tunnel run` anywhere except the top-level DinD host container.
- Do not move the active Python consumer back into a container.
- Do not pretend PostgreSQL or Bolt are HTTP services.
- Do not reintroduce extra DinD child containers unless this file is intentionally updated first.
- Do not rely on `/var/lib/docker` alone for database durability.

## Expected Workflow
1. `python3 src/utils/prepare_runtime.py`
2. `docker volume create tunnels-experiment-persistent-service-data || true`
3. `docker compose up --build -d`
4. `python3 src/utils/wait_for_stack.py --run-ts <RUN_TS>`
5. `.venv/bin/python src/experiment_runner.py --run-ts <RUN_TS>`
6. `python3 src/utils/smoke_test.py --run-ts <RUN_TS>`
7. `python3 src/utils/append_runlog.py --run-ts <RUN_TS>`
8. `python3 src/utils/write_summary.py --run-ts <RUN_TS>`
9. `docker compose down --remove-orphans --volumes`

The default one-command end-to-end path is:
- `./start_e2e.sh`

The optional manual local-bridge path is:
- `.venv/bin/python src/bridge/start_local_bridges.py`

The operator-focused host-testing path is:
- `./start_host.sh`

## Validation Discipline
- Run `python3 src/utils/prepare_runtime.py` before Compose commands.
- Use `docker compose config -q` to validate Compose without printing secret-expanded config.
- Use `./start_e2e.sh` for the normal integration path.
- Use `python3 src/utils/smoke_test.py --run-ts ...` for report validation when debugging.
- For architecture research, verify claims against current Cloudflare primary-source docs before changing the repo objective or topology.

## Definition Of Done
- `python3 src/utils/prepare_runtime.py` succeeds against the local `tunnels.json`.
- `docker compose up --build -d` brings up only `dind-host-container`.
- `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'` shows no host bindings.
- Neo4j and PostgreSQL retain prior data after the outer stack is torn down and started again.
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
  - purpose: PostgreSQL write/read proof cycle plus the lightweight manual bridge verification query.
  - reason: keeps PostgreSQL-specific proof logic out of both the coordinator and the bridge transport layer.
  - status: `Mergeable`

- `src/simulators/neo4j_bolt.py`
  - purpose: Neo4j Bolt write/read proof cycle plus the lightweight manual bridge verification query.
  - reason: keeps Bolt-specific proof logic out of both the coordinator and the bridge transport layer.
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
- `src/bridge/start_local_bridges.py`
  - purpose: manual CLI that exposes local PostgreSQL and Neo4j Bolt ports for DBeaver and Bolt consumers.
  - reason: supports the non-automated manual client workflow without client-side `cloudflared`.
  - status: `Optional`

- `src/bridge/local_bridges.py`
  - purpose: shared bridge specs and runtime host loading for the manual bridge CLI.
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
- keep `src/bridge/start_local_bridges.py` only if the manual DBeaver/Bolt workflow remains a supported feature;
- drop `append_runlog.py`, `write_summary.py`, and possibly `smoke_test.py` if strict tracked run history is no longer required.

## Verified State
- Verified automated run identifier: `260320_221626`
- Verified restart-only persistence run identifier: `260320_221836`
- Verified outcome:
  - `./start_e2e.sh --duration-seconds 1 --keep-up` completed end to end with a fresh persistent data volume;
  - `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'` showed no host bindings;
  - Neo4j HTTPS succeeded over `c74d8a4e03e6.ratio1.link`;
  - Neo4j Bolt succeeded through the host-side local bridge on `127.0.0.1:17687`;
  - PostgreSQL succeeded through the host-side local bridge on `127.0.0.1:15432`;
  - the host-side experiment completed three proof cycles and produced `3` PostgreSQL rows plus `3` Neo4j `ExperimentEvent` nodes;
  - `docker compose down --remove-orphans --volumes` removed the outer stack while leaving external volume `tunnels-experiment-persistent-service-data` intact;
  - after restart-only bring-up in run `260320_221836`, `pgsql-service` logged `reusing persisted PostgreSQL data from /persistent-service-data/postgres`;
  - after restart-only bring-up in run `260320_221836`, `neo4j-service` logged `reusing persisted Neo4j data from /persistent-service-data/neo4j`;
  - before any second-run proof workload, PostgreSQL still returned total row count `3`;
  - before any second-run proof workload, Neo4j still returned total `ExperimentEvent` count `3`.
- Persistence model:
  - `dind-host-container` mounts external volume `tunnels-experiment-persistent-service-data` at `/persistent-service-data`;
  - `neo4j-demo` binds `/persistent-service-data/neo4j` to `/data`;
  - `postgres-demo` binds `/persistent-service-data/postgres` to `/var/lib/postgresql/data/pgdata`;
  - outer `docker compose down --remove-orphans --volumes` removes ephemeral DinD Docker state but leaves the external database volume intact.
