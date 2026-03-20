# DOCUMENTATION.md

## Status
- Phase: verified working demo
- Current objective: keep the generic service-discovery DinD host layout stable and reproducible

## Intended Architecture
- Top-level Compose service:
  - `dind-host-container`
- Direct child database containers started by `dind-host-container`:
  - `neo4j-demo`
  - `postgres-demo`
- Host-side consumer:
  - `src/experiment_runner.py`

## Host-Side Code Layout
- Shared helpers and utility entrypoints:
  - `src/utils/`
- Universal TCP-over-WebSocket bridge:
  - `src/bridge/`
- Dedicated service simulators:
  - `src/simulators/`
- Experiment coordinator:
  - `src/experiment_runner.py`

## DinD Host Image Layout
- `docker/dind/entrypoint.sh`
  - starts `dockerd` inside `dind-host-container`
- `docker/dind/orchestrator.sh`
  - discovers every `docker/dind/servers/*.sh`, launches them, and writes the topology-ready marker
- `docker/dind/servers/neo4j.sh`
  - starts Neo4j and its two tunnels
- `docker/dind/servers/pgsql.sh`
  - starts PostgreSQL and its tunnel

## Key Rules
- No top-level Compose port is published to the real machine.
- All outbound service exposure happens through `cloudflared tunnel run` inside `dind-host-container`.
- The database containers publish only to `127.0.0.1` inside `dind-host-container`.
- The real machine reaches PostgreSQL and Neo4j Bolt through host-side local TCP bridges opened by `src/experiment_runner.py`.
- The real machine reaches Neo4j HTTPS directly through the public tunnel hostname.

## Tunnel Transport Notes
- `cloudflared tunnel run --url http://127.0.0.1:17474` publishes Neo4j HTTP in standard HTTP proxy mode.
- `cloudflared tunnel run --url tcp://127.0.0.1:17687` and `tcp://127.0.0.1:15432` publish Bolt and PostgreSQL in Cloudflare TCP mode.
- In that TCP mode, the public hostname is not a native raw database socket. The client side uses a WebSocket transport, which is why the bridge code under `src/bridge/` exposes local TCP listeners and relays those local byte streams to `wss://<public-hostname>`.
- This is why DBeaver-style and Bolt-driver-style clients talk to `127.0.0.1:<bridge-port>` on the real machine in this demo, not directly to the public hostname.

## Manual Direct-Client Access With The Python Bridge
- The repository supports a client-side-cloudflared-free manual bridge helper under `src/utils/start_local_bridges.py`.
- Verified behavior on 2026-03-20:
  - direct PostgreSQL to `60bf15690490.ratio1.link:443` failed with `invalid response to SSL negotiation: H`;
  - direct Neo4j Bolt to `99c7e7089d1b.ratio1.link:443` failed because the endpoint `looks like HTTP`;
  - live manual bridge verification run `260320_201234` using `.venv/bin/python src/utils/start_local_bridges.py --verify --duration-seconds 1 --run-ts 260320_201234` succeeded with a real PostgreSQL `SELECT 1` and a real Neo4j Bolt `RETURN 1`;
- This means DBeaver can point at `127.0.0.1:55432` and the Neo4j Python driver can point at `bolt://127.0.0.1:57687` using only the repository's Python bridge and the public tunnel FQDNs.
- There is no supported way for DBeaver or a Bolt driver to talk native PostgreSQL/Bolt directly to the current public `*.ratio1.link` hostname because published TCP apps terminate at Cloudflare's HTTP/WebSocket edge.
- The supported repository answer for local database tools is therefore the Python bridge CLI, not a client-side `cloudflared` helper.

## Expected Workflow
1. `python3 src/utils/prepare_runtime.py`
2. `./start.sh`
3. Optional manual local bridge: `.venv/bin/python src/utils/start_local_bridges.py`
4. Inspect `_logs/raw/` for raw artifacts.
5. Inspect `_logs/RUNLOG.md` for the appended end-to-end result.

## Verified Run
- Verified automated run identifier: `260320_201433`
- Verified outcome:
  - `./start.sh --duration-seconds 1` completed end to end and then stopped the stack automatically;
  - the separate manual Python bridge verification run `260320_201234` passed against the live stack before the automated run;
  - the host-side Python entrypoints ran from repo-root `src/`;
  - the top-level `dind-host-container` remained healthy during the run;
  - `docker inspect` reported no host port bindings for `dind-host-container`;
  - the in-container orchestrator discovered the packaged service scripts dynamically and wrote an aggregated topology marker;
  - Neo4j HTTPS succeeded over `c74d8a4e03e6.ratio1.link`;
  - Neo4j Bolt succeeded through the host-side local bridge on `127.0.0.1:17687`;
  - PostgreSQL succeeded through the host-side local bridge on `127.0.0.1:15432`;
  - the host-side experiment completed three write/read cycles during the short regression-validation run.

## Note On `docker compose ps`
- The base `docker:dind` image exposes `2375/tcp` and `2376/tcp` as image metadata.
- `docker compose ps` may therefore show `2375-2376/tcp` in the `PORTS` column even when nothing is published to the real machine.
- The authoritative check for this repository is `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'`, which must show no host bindings.
