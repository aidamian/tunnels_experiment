# PLANNING.md

## Objective
Build a reproducible demo showing that:
- a single top-level Docker-in-Docker host container can run all outbound Cloudflare Tunnel processes;
- Neo4j and PostgreSQL can each run as direct child containers of that DinD host;
- no service port is published from the top-level DinD host container to the real machine;
- a Python script running directly on the real machine can behave like external clients and reach the databases only through the three public tunnel URLs.

## Inputs And Constraints
- Runtime tunnel secrets live in `tunnels.json` and must stay untracked.
- The top-level Compose stack must expose no `ports:` entries to the real machine.
- The top-level container is the only place where `cloudflared tunnel run` is allowed.
- The top-level DinD image must be self-contained and include:
  - an entrypoint that starts the inner Docker daemon;
  - a separate orchestration script;
  - per-service scripts under `servers/`.
- Neo4j must run as a direct child container of the top-level DinD host.
- PostgreSQL must run as a direct child container of the top-level DinD host.
- The host-side Python runner must use:
  - Neo4j HTTPS directly over the public hostname;
  - Neo4j Bolt through a host-side local TCP bridge that terminates into the public tunnel hostname;
  - PostgreSQL through a host-side local TCP bridge that terminates into the public tunnel hostname.
- Logs must be separated:
  - runtime artifacts under `_logs/raw/`;
  - end-to-end run history appended to `_logs/RUNLOG.md`;
  - tracked iteration summary in `_logs/YYMMDD_HHMMSS_summary.md`.

## Primary-Source Findings
### Cloudflare Tunnel
- `cloudflared tunnel run --token ... --url ...` creates an outbound-only connector from the private network to the Cloudflare edge.
- Published TCP applications are carried over a WebSocket transport at the public hostname rather than accepting native database handshakes directly.
- A small host-side TCP bridge can make those published TCP applications appear as ordinary local sockets for tools such as DBeaver or native database drivers.

### Docker And DinD
- Nested Docker requires privileged containers and conservative storage settings.
- The DinD host can run its child database containers directly and publish their ports only to `127.0.0.1` inside the DinD host container.
- Keeping the Docker daemon private to the container and avoiding Compose `ports:` entries prevents any service exposure to the real machine.

### Database Containers
- Neo4j uses HTTP on `7474` and Bolt on `7687`.
- PostgreSQL uses TCP on `5432`.
- Deterministic demo credentials are acceptable here because they are scoped to a disposable local experiment and are not tunnel secrets.

## Architecture
### Real machine
1. `start.sh`
   - prepares runtime files;
   - brings up the top-level Compose stack;
   - waits for DinD-host topology readiness;
   - runs the host-side Python experiment for about 30 seconds;
   - validates the report;
   - appends `_logs/RUNLOG.md`;
   - writes a tracked `_logs/YYMMDD_HHMMSS_summary.md`;
   - stops the stack unless explicitly told to keep it running.

2. `scripts/sre/run_experiment.py`
   - primary operator entrypoint that runs directly on the real machine;
   - starts two host-side local TCP bridge listeners on `127.0.0.1`;
   - bridges those listeners to the public Bolt and PostgreSQL tunnel hostnames over WebSocket;
   - simulates:
     - a DBeaver-style PostgreSQL client;
     - an external Bolt client;
     - a direct HTTPS Neo4j API consumer.
   - compatibility wrapper remains available at `scripts/run_experiment.py`.

### Top-level Compose service
1. `dind-host-container`
   - single top-level Docker-in-Docker container;
   - publishes no ports to the real machine;
   - starts its own Docker daemon through an in-image entrypoint;
   - runs an in-image orchestrator;
   - starts `neo4j-demo` and `postgres-demo` as direct child containers;
   - runs all three outbound `cloudflared tunnel run` processes.

### In-image orchestration layout
1. `docker/dind/entrypoint.sh`
   - starts `dockerd`;
   - waits for `docker info`;
   - hands off to the orchestrator.

2. `docker/dind/orchestrator.sh`
   - launches `servers/neo4j.sh` and `servers/pgsql.sh`;
   - waits for ready markers;
   - writes the topology-ready file used by the host-side wait step.

3. `docker/dind/servers/neo4j.sh`
   - starts `neo4j-demo`;
   - publishes `7474` and `7687` only to `127.0.0.1` inside `dind-host-container`;
   - starts the Neo4j HTTPS and Bolt tunnels.

4. `docker/dind/servers/pgsql.sh`
   - starts `postgres-demo`;
   - publishes `5432` only to `127.0.0.1` inside `dind-host-container`;
   - starts the PostgreSQL TCP tunnel.

### Tunnel assignment
1. Tunnel 1 -> Neo4j HTTPS
2. Tunnel 2 -> Neo4j Bolt/TCP
3. Tunnel 3 -> PostgreSQL TCP
4. Tunnel 4 -> reserved and unused by the automated experiment

## Demo Flow
1. `python3 scripts/sre/prepare_runtime.py`
2. `docker compose up --build -d`
3. `dind-host-container` starts its in-image entrypoint and private Docker daemon.
4. The in-image orchestrator starts:
   - `neo4j-demo`;
   - `postgres-demo`;
   - three outbound `cloudflared tunnel run` processes through the per-service scripts.
5. `scripts/sre/run_experiment.py` starts two host-side local TCP bridges on the real machine:
   - PostgreSQL bridge for the DBeaver-style flow;
   - Neo4j Bolt bridge for the external Bolt-app flow.
6. The host script performs about three timed cycles over about 30 seconds:
   - insert and read PostgreSQL rows;
   - create and read Neo4j nodes and relationships over Bolt;
   - read the same Neo4j graph over HTTPS.
7. Validation confirms:
   - all writes and reads succeeded;
   - the top-level container published no ports;
   - logs and reports were written to the expected locations.

## Milestones
### Milestone 1: Runtime and logging scaffolding
Acceptance criteria:
- `scripts/sre/prepare_runtime.py` generates `.runtime/tunnels.env` without leaking secrets.
- `_logs/raw/` exists for runtime artifacts.
- `_logs/RUNLOG.md` exists for appended end-to-end summaries.

Validation:
- `python3 scripts/sre/prepare_runtime.py`

### Milestone 2: DinD host orchestration
Acceptance criteria:
- `docker-compose.yml` defines only the top-level `dind-host-container`.
- The Compose service publishes no host ports.
- The DinD image contains the entrypoint, orchestrator, and per-service scripts.
- The top-level startup flow launches `neo4j-demo` and `postgres-demo` directly.

Validation:
- `docker compose config -q`

### Milestone 3: Host-side client simulation
Acceptance criteria:
- `scripts/sre/run_experiment.py` runs on the real machine.
- It uses the three public tunnel hostnames from `.runtime/tunnels.env`.
- It simulates:
  - DBeaver-style PostgreSQL access through a host-side local TCP bridge;
  - a Bolt client through a host-side local TCP bridge;
  - direct Neo4j HTTPS access.
- It writes a machine-readable report under `_logs/raw/`.

Validation:
- `python3 scripts/sre/run_experiment.py --help`

### Milestone 4: End-to-end verification and documentation
Acceptance criteria:
- `./start.sh` runs the full demo in one command.
- `python3 scripts/sre/smoke_test.py` passes against the generated report.
- `README.md`, `DOCUMENTATION.md`, `_logs/RUNLOG.md`, and the timestamped `_logs/*_summary.md` reflect the verified topology.

Validation:
- `./start.sh`
- `python3 scripts/sre/smoke_test.py`

## Success Criteria
The demo is successful when all of the following hold:
- `python3 scripts/sre/prepare_runtime.py` succeeds.
- `docker compose up --build -d` brings up only `dind-host-container`.
- `docker compose ps` shows no published ports for `dind-host-container`.
- Neo4j HTTPS works through tunnel 1.
- Neo4j Bolt works through tunnel 2 via a host-side local TCP bridge.
- PostgreSQL works through tunnel 3 via a host-side local TCP bridge.
- The host-side experiment writes and reads new timestamped proof records in both databases.
- `_logs/raw/` contains run-specific artifacts.
- `_logs/RUNLOG.md` contains the end-to-end result.

## Risks And Mitigations
- DinD startup can be slow:
  - Mitigation: explicit readiness polling and health files.
- TCP tunnel hostnames are not native raw sockets:
  - Mitigation: the host script exposes local TCP bridge ports that translate native client traffic into the published WebSocket transport.
- Host local forward ports can collide with existing services:
  - Mitigation: reserve dedicated high-numbered local ports and fail clearly if they are already in use.
- Secret leakage through verbose validation:
  - Mitigation: use `docker compose config -q` instead of printing expanded config.

## Sources
- Cloudflare Tunnel overview: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- Cloudflare published application protocols: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/
- Cloudflare arbitrary TCP with client-side `cloudflared`: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/
- PostgreSQL official image reference: https://hub.docker.com/_/postgres
