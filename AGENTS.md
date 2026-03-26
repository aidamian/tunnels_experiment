# AGENTS.md

## Purpose

This repository demonstrates Cloudflare Tunnel across two Docker-in-Docker hosts plus a real-machine Python client:

- `dind-host-server` publishes origin services
- `dind-host-app` consumes the PostgreSQL tunnel through a local Python bridge and republishes a web UI
- `clients/` proves the original host-side flow directly from the real machine

## Durable Memory

Read these files before making non-trivial changes:

- `IMPLEMENTATION.md`
- `PLAN.md` when a refactor is in progress
- `_logs/YYMMDD_HHMMSS_*.md`

## Steady-State Topology

- `servers/docker-compose.yml`
  - defines top-level `dind-host-server`
- `servers/docker/dind/servers/neo4j.sh`
  - starts `neo4j-demo` and its HTTPS and Bolt tunnels when enabled
- `servers/docker/dind/servers/pgsql.sh`
  - starts `postgres-demo` and its TCP tunnel when enabled
- `apps/docker-compose.yml`
  - defines top-level `dind-host-app`
- `apps/docker/dind/servers/pgadmin.sh`
  - starts the app-host Python bridge, verifies PostgreSQL through it, starts `pgadmin-demo`, and publishes the app HTTPS UI
- `clients/src/experiment_runner.py`
  - host-side proof runner
- `clients/services.json`
  - client-side public service catalog and local bridge defaults

## First-Principles Rules

1. Define the client contract precisely.
   - `No-bridge` means a normal client points at an FQDN and speaks its native protocol directly.
   - Any requirement for a local Python bridge, client-side `cloudflared`, or WARP is not `no-bridge`.
2. Preserve protocol identity.
   - HTTP/HTTPS and native PostgreSQL/Bolt/TCP are not interchangeable.
3. Separate Cloudflare product families.
   - Tunnel published applications
   - Tunnel private-network routing with WARP
   - Spectrum native TCP/UDP proxying
4. Reject wishful equivalence.
   - Cloudflare Tunnel published TCP hostnames are not native public PostgreSQL or Bolt sockets.

## Builder-Critic Loop

1. Builder pass: read `IMPLEMENTATION.md` and complete one coherent change.
2. Validation pass: run the relevant commands listed there.
3. Critic pass: check separation, topology, secrets, and verification.
4. Documentation pass: update `IMPLEMENTATION.md`, `README.md`, and append a timestamped summary under root `_logs/`.

## Guardrails

- `servers/tunnels.json` contains live tunnel tokens. Never print, commit, or copy those tokens into tracked files.
- `servers/src/utils/prepare_runtime.py` generates `servers/.runtime/dind.env`.
- `apps/src/utils/prepare_runtime.py` generates `apps/.runtime/dind.env` from root-passed derived values.
- `clients/services.json` is client-owned and must drive client bridge defaults.
- No sharing of runtime files or raw-log folders between `servers/`, `apps/`, and `clients/` is permitted.
- Root `_logs/` is for tracked markdown only, not active runtime output.
- The tunnel-role mapping is fixed unless `IMPLEMENTATION.md` is intentionally updated:
  - tunnel 1: Neo4j HTTPS
  - tunnel 2: Neo4j Bolt/TCP
  - tunnel 3: PostgreSQL TCP
  - tunnel 4: app HTTPS UI
- Keep orchestration reproducible with `docker compose`, scripts, and tracked markdown.

## Definition Of Done

- `python3 servers/src/utils/prepare_runtime.py` succeeds against `servers/tunnels.json`
- `./start_e2e.sh --duration-seconds 1` still proves:
  - Neo4j over public HTTPS
  - Neo4j over Bolt through the client-side local bridge
  - PostgreSQL over TCP through the client-side local bridge
- `./start_apps.sh` proves:
  - `dind-host-server` can launch only `pgsql`
  - `dind-host-app` can bridge to the public PostgreSQL tunnel hostname
  - `pgadmin-demo` can reach PostgreSQL through that bridge
  - the public app UI responds over tunnel 4
- both top-level Compose services publish no ports to the real machine
- `IMPLEMENTATION.md` and the current timestamped root `_logs/*.md` summary reflect the verified state
