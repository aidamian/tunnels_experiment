# tunnels_experiment

This repository demonstrates Cloudflare Tunnel across three isolated worlds:

- `servers/` for origin services inside `dind-host-server`
- `apps/` for bridge-backed app containers inside `dind-host-app`
- `clients/` for the real-machine Python proof client

## Layout

```text
.
|-- start_e2e.sh
|-- start_host.sh
|-- start_apps.sh
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
|-- apps/
|   |-- docker-compose.yml
|   |-- .runtime/
|   |-- _logs/raw/
|   `-- src/
`-- _logs/
```

- `servers/` owns the origin DinD host, tunnel inventory, and server runtime/log output.
- `apps/` owns the consumer DinD host, the internal Python bridge, and app runtime/log output.
- `clients/` owns the real-machine proof client and `clients/services.json`.
- Root `_logs/` stays documentation-only.

## Topology

```text
Real Machine
|
|-- start_e2e.sh / start_host.sh
|    `-- clients/src/experiment_runner.py
|         |-- HTTPS -> Neo4j public hostname
|         |-- local TCP bridge -> wss://Neo4j Bolt public hostname
|         `-- local TCP bridge -> wss://PostgreSQL public hostname
|
|-- start_apps.sh
|    |-- docker compose --project-directory servers -f servers/docker-compose.yml
|    |    `-- dind-host-server
|    |         |-- postgres-demo
|    |         `-- cloudflared tunnel run -> PostgreSQL TCP
|    `-- docker compose --project-directory apps -f apps/docker-compose.yml
|         `-- dind-host-app
|              |-- python bridge -> wss://PostgreSQL public hostname
|              |-- pgadmin-demo -> 127.0.0.1:55432 inside dind-host-app
|              `-- cloudflared tunnel run -> pgAdmin HTTPS UI
```

The critical rule is unchanged: neither top-level DinD host publishes service ports to the real machine.

## Tunnel Roles

- tunnel 1: Neo4j HTTPS
- tunnel 2: Neo4j Bolt/TCP
- tunnel 3: PostgreSQL TCP
- tunnel 4: app HTTPS UI

## Important Transport Rules

- Neo4j HTTPS is a normal public HTTPS application.
- Neo4j Bolt and PostgreSQL are Tunnel-published TCP applications carried to consumers over WebSocket.
- `clients/src/bridge/universal.py` converts those public TCP tunnel hostnames into localhost TCP sockets for the real-machine client.
- `apps/src/bridge/universal.py` does the same inside `dind-host-app`, so `pgadmin-demo` can connect to `127.0.0.1:55432` and behave as if PostgreSQL were local to that DinD host.

## Main Commands

Full host-side proof:

```bash
./start_e2e.sh --duration-seconds 1
```

Manual host bridge workflow:

```bash
timeout -s INT 120 ./start_host.sh --verify
```

Server plus app flow:

```bash
./start_apps.sh
```

Keep the app flow up for manual inspection:

```bash
./start_apps.sh --keep-up
```

## Verified State

The repository is currently verified to demonstrate:

- selective origin startup on `dind-host-server`
- PostgreSQL over tunnel 3 with no host port publishing
- an app-host local Python bridge that relays to the PostgreSQL tunnel hostname
- `pgadmin-demo` using that bridge inside `dind-host-app`
- a public HTTPS UI on tunnel 4 that responds with `PING` at `/misc/ping`
- the original real-machine Neo4j/PostgreSQL proof path still passing
