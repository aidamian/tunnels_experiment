# tunnels_experiment

This repository demonstrates Cloudflare Tunnel access to services running inside a single Docker-in-Docker host, with a strict split between server-side and client-side artifacts.

## Layout

```text
.
|-- start_e2e.sh
|-- start_host.sh
|-- clients/
|   |-- services.json
|   |-- requirements.txt
|   |-- _logs/raw/
|   `-- src/
|-- servers/
|   |-- docker-compose.yml
|   |-- tunnels.json
|   |-- .runtime/
|   |-- _logs/raw/
|   `-- docker/
`-- _logs/
```

- `servers/` owns Docker Compose, the DinD image, `tunnels.json`, generated server runtime state, and server raw logs.
- `clients/` owns `services.json`, the host-side Python code, the client virtualenv inputs, and client raw logs.
- Root `_logs/` is documentation-only. Runtime logs now live only under `clients/_logs/raw/` and `servers/_logs/raw/`.

## Topology

```text
Real Machine
|
|-- start_e2e.sh / start_host.sh
|-- clients/src/experiment_runner.py
|    |-- HTTPS -> Neo4j public hostname
|    |-- local TCP bridge -> wss://Neo4j Bolt public hostname
|    `-- local TCP bridge -> wss://PostgreSQL public hostname
|
`-- docker compose --project-directory servers -f servers/docker-compose.yml
     `-- dind-host-container
          |-- cloudflared tunnel run -> Neo4j HTTPS
          |-- cloudflared tunnel run -> Neo4j Bolt
          |-- cloudflared tunnel run -> PostgreSQL
          |-- neo4j-demo
          `-- postgres-demo
```

The critical rule remains unchanged: the top-level `dind-host-container` publishes no service ports to the real machine.

## Ownership Rules

- Client code must not import from `servers/`.
- Server code must not import from `clients/`.
- Client code must not read `servers/.runtime/` or `servers/_logs/raw/`.
- Server code must not read `clients/services.json` or `clients/_logs/raw/`.
- Root scripts may coordinate both worlds, but they pass values through CLI arguments rather than shared runtime files.

## Client Configuration

`clients/services.json` is the client-owned service catalog. It defines:

- stable service keys
- public hostnames or URLs
- which services require local bridges
- default client-side local bridge ports
- operator-facing bridge purpose text

Current defaults:

- Neo4j HTTPS: direct `https://...`
- Neo4j Bolt bridge: `127.0.0.1:57687`
- PostgreSQL bridge: `127.0.0.1:55432`

Manual bridge CLI overrides are still available through `--postgres-port` and `--neo4j-port`.

## Server Runtime

Server runtime generation is owned by:

```bash
python3 servers/src/utils/prepare_runtime.py
```

It reads `servers/tunnels.json` and writes:

- `servers/.runtime/dind.env`
- `servers/_logs/raw/`

It does not generate any client file.

## Client Runtime

Client runtime input is fully owned by:

- `clients/services.json`
- `clients/requirements.txt`
- `clients/.venv/`
- `clients/_logs/raw/`

The client no longer reads server-generated `public_hosts.json` or server topology markers.

## Why TCP Still Needs A Bridge

Cloudflare Tunnel published TCP applications are exposed to clients over a WebSocket carrier. That means:

- Neo4j HTTPS works directly as a public HTTPS application.
- Neo4j Bolt and PostgreSQL do not appear as native public raw TCP sockets.
- The client therefore needs a local TCP-to-WebSocket bridge.

This repository keeps that bridge inside `clients/src/bridge/universal.py` and configures it from `clients/services.json`.

## Logging

The refactor also changed runtime logging:

- root shell entrypoints emit ANSI-colored step logs
- server shell logs emit ANSI-colored scoped logs under `servers/_logs/raw/`
- client Python bridge logs emit ANSI-colored `.log` streams under `clients/_logs/raw/`
- JSON, Markdown, and env files remain plain text

## Main Commands

Full automated proof:

```bash
./start_e2e.sh --duration-seconds 1
```

Manual bridge workflow:

```bash
timeout -s INT 120 ./start_host.sh --verify
```

Manual bridge CLI directly:

```bash
clients/.venv/bin/python clients/src/bridge/start_local_bridges.py --verify
```

Compose validation:

```bash
docker compose --project-directory servers -f servers/docker-compose.yml config -q
```

## Verified Refactor State

The current refactor has been verified to preserve:

- Neo4j over public HTTPS
- Neo4j Bolt through the client-side local bridge
- PostgreSQL through the client-side local bridge
- no host port publishing from `dind-host-container`
- separate client and server runtime/log ownership
