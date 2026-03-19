# DOCUMENTATION.md

## Status
- Phase: verified working demo
- Current objective: keep the direct child-container DinD host layout stable and reproducible

## Intended Architecture
- Top-level Compose service:
  - `dind-host-container`
- Direct child database containers started by `dind-host-container`:
  - `neo4j-demo`
  - `postgres-demo`
- Host-side consumer:
  - `scripts/run_experiment.py`

## DinD Host Image Layout
- `docker/dind/entrypoint.sh`
  - starts `dockerd` inside `dind-host-container`
- `docker/dind/orchestrator.sh`
  - launches the per-service scripts and writes the topology-ready marker
- `docker/dind/servers/neo4j.sh`
  - starts Neo4j and its two tunnels
- `docker/dind/servers/pgsql.sh`
  - starts PostgreSQL and its tunnel

## Key Rules
- No top-level Compose port is published to the real machine.
- All outbound service exposure happens through `cloudflared tunnel run` inside `dind-host-container`.
- The database containers publish only to `127.0.0.1` inside `dind-host-container`.
- The real machine reaches PostgreSQL and Neo4j Bolt through host-side local TCP bridges opened by `scripts/run_experiment.py`.
- The real machine reaches Neo4j HTTPS directly through the public tunnel hostname.

## Expected Workflow
1. `python3 scripts/prepare_runtime.py`
2. `./start.sh`
3. Inspect `_logs/raw/` for raw artifacts.
4. Inspect `_logs/RUNLOG.md` for the appended end-to-end result.

## Verified Run
- Verified run identifier: `260319_191602`
- Verified outcome:
  - `./start.sh` completed end to end and then stopped the stack automatically;
  - the top-level `dind-host-container` remained healthy during the run;
  - `docker inspect` reported no host port bindings for `dind-host-container`;
  - Neo4j HTTPS succeeded over `c74d8a4e03e6.ratio1.link`;
  - Neo4j Bolt succeeded through the host-side local bridge on `127.0.0.1:17687`;
  - PostgreSQL succeeded through the host-side local bridge on `127.0.0.1:15432`;
  - the host-side experiment completed four write/read cycles over about 30 seconds.

## Note On `docker compose ps`
- The base `docker:dind` image exposes `2375/tcp` and `2376/tcp` as image metadata.
- `docker compose ps` may therefore show `2375-2376/tcp` in the `PORTS` column even when nothing is published to the real machine.
- The authoritative check for this repository is `docker inspect dind-host-container --format '{{json .NetworkSettings.Ports}}'`, which must show no host bindings.
