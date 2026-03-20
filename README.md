# tunnels_experiment

This repository demonstrates a tunnel-only access pattern:

1. A single top-level Docker-in-Docker host container runs all outbound Cloudflare Tunnel connectors.
2. Inside that container, the DinD daemon starts `neo4j-demo` and `postgres-demo` directly as child containers.
3. A Python script runs directly on the real machine and reaches those databases only through the public tunnel hostnames and local TCP bridges.

The critical rule is simple: the top-level DinD host container publishes no service ports to the real machine. The only path out is Cloudflare Tunnel.

## Topology

```text
Real Machine
|
|-- start_e2e.sh
|-- start_host.sh
|-- src/experiment_runner.py
|    |-- HTTPS -> Neo4j public hostname
|    |-- local TCP bridge -> wss://Neo4j Bolt public hostname
|    `-- local TCP bridge -> wss://PostgreSQL public hostname
|
`-- docker compose
     `-- dind-host-container
          |-- entrypoint.sh -> starts dockerd
          |-- orchestrator.sh -> discovers servers/*.sh dynamically
          |-- cloudflared tunnel run -> Neo4j HTTPS
          |-- cloudflared tunnel run -> Neo4j Bolt
          |-- cloudflared tunnel run -> PostgreSQL
          |-- neo4j-demo
          `-- postgres-demo
```

## DinD Host Image Layout

The DinD host image is deliberately self-contained:

- `entrypoint.sh`
  - starts the Docker daemon inside `dind-host-container`
- `orchestrator.sh`
  - discovers `servers/*.sh`, coordinates startup, and writes the aggregated topology marker
- `servers/neo4j.sh`
  - starts Neo4j and both Neo4j tunnels
- `servers/pgsql.sh`
  - starts PostgreSQL and its tunnel

## Host-Side Script Layout

The host-side Python code now has a single flat source tree at repo-root `src/`:

- `src/utils/`
  - runtime prep, report helpers, Docker polling, shared config, and the manual local-bridge CLI
- `src/bridge/`
  - the universal TCP-to-WebSocket bridge used for any published TCP service
- `src/simulators/`
  - separate PostgreSQL, Neo4j Bolt, and Neo4j HTTPS proof logic
- `src/experiment_runner.py`
  - the top-level experiment coordinator

## Why It Works

Step by step:

1. `dind-host-container` starts a private nested Docker daemon.
2. The in-image `entrypoint.sh` hands control to `orchestrator.sh` after `dockerd` is healthy.
3. `orchestrator.sh` launches `servers/neo4j.sh` and `servers/pgsql.sh`.
4. Those server scripts run `neo4j-demo` and `postgres-demo` directly as child containers of the DinD host.
5. Each database container publishes only to `127.0.0.1` inside `dind-host-container`, not to the real machine.
6. The same server scripts start the required `cloudflared tunnel run` processes and point them at those loopback-only origins.
7. Because the top-level Compose service has no `ports:` section, the real machine still receives no direct Docker port mapping.
8. For TCP protocols, the host-side Python bridge opens ordinary local sockets so tools such as DBeaver or Neo4j Bolt applications can connect as if the services were local.

## Cloudflare Tunnel: HTTP Vs TCP

The short answer to "aren't Cloudflare tunnels HTTPS by definition?" is no.

- For Neo4j HTTP we run `cloudflared tunnel run --url http://127.0.0.1:17474`.
  The public side is a normal `https://...` hostname, and Cloudflare proxies HTTP to the local Neo4j HTTP port.
- For Neo4j Bolt and PostgreSQL we run `cloudflared tunnel run --url tcp://127.0.0.1:17687` and `cloudflared tunnel run --url tcp://127.0.0.1:15432`.
  Those are not exposed as native raw database sockets on the public Internet. Cloudflare's published TCP applications are carried through a WebSocket transport on the client-facing side.
- That is why the host-side experiment runner in `src/experiment_runner.py` creates local TCP listeners on `127.0.0.1` and relays those byte streams to `wss://<public-hostname>`.
  Local clients still speak ordinary Bolt or PostgreSQL to the bridge, while the bridge handles the WebSocket carrier required by Cloudflare's TCP mode.

So the public hostname is a Cloudflare HTTPS/TLS endpoint, but the payload inside that connection can still be a raw TCP application such as Bolt or PostgreSQL.

This repository makes that transport explicit by implementing the client-side bridge in Python, so local tools can work without any client-side `cloudflared` dependency.

## Runtime File Separation

Runtime state is split deliberately:

- `.runtime/dind.env`
  - used by `docker compose` and the DinD container
  - contains `RUN_TS`, demo credentials, public hosts, and tunnel tokens
- `.runtime/public_hosts.json`
  - used by host-side Python clients and bridges
  - contains only the public FQDNs needed by the client side

That split keeps the host/client side from reading the DinD tunnel-token file.

## Direct DBeaver And Bolt Access With The Python Bridge

What this means in practice:

- Direct `psycopg` or Bolt connections to `*.ratio1.link:443` do not work in this topology because the public endpoint is speaking Cloudflare's HTTP/WebSocket edge protocol, not a native raw PostgreSQL or Bolt socket.
- The supported repo solution is a small Python bridge that exposes ordinary localhost TCP ports and relays those byte streams to the public tunnel FQDNs over WebSocket.

The repository now provides a tracked helper for that path:

```bash
.venv/bin/python src/utils/start_local_bridges.py
```

Optional proof path with the repo virtualenv:

```bash
.venv/bin/python src/utils/start_local_bridges.py --verify --duration-seconds 1
```

This starts two local forwards:

- PostgreSQL: `127.0.0.1:55432`
- Neo4j Bolt: `127.0.0.1:57687`

DBeaver can use the PostgreSQL forward with these settings:

- host: `127.0.0.1`
- port: `55432`
- database: `tunnel_demo`
- user: `tunnel_demo`
- password: `tunnel-demo-postgres`
- SSL: disable

Python Neo4j code can use the Bolt forward like this:

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
  "bolt://127.0.0.1:57687",
  auth=("neo4j", "tunnel-demo-neo4j"),
)
```

Press `Ctrl+C` in the terminal running `start_local_bridges.py`.

There is still no supported way to point DBeaver or a Bolt driver directly at the current public `*.ratio1.link` hostname as if it were a native PostgreSQL or Bolt socket. The bridge remains necessary because the client-facing transport is WebSocket-based.

## Why `127.0.0.1:` Matters

Inside `dind-host-container`, the service scripts use:

- `docker run -p 127.0.0.1:17474:7474 -p 127.0.0.1:17687:7687 neo4j`
- `docker run -p 127.0.0.1:15432:5432 postgres`

and not just:

- `docker run -p 17474:7474 ...`
- `docker run -p 17687:7687 ...`
- `docker run -p 15432:5432 ...`

The reason is scope.

- `-p 15432:5432` binds `0.0.0.0:15432` inside the DinD host container.
- `-p 127.0.0.1:15432:5432` binds only loopback inside the DinD host container.

In this repository, the `docker run` host is not the real machine. It is `dind-host-container` itself.

That means:

- `-p 15432:5432` would make PostgreSQL reachable on every interface of `dind-host-container`, including its non-loopback container IP.
- `-p 127.0.0.1:15432:5432` makes PostgreSQL reachable only to processes running inside that same DinD host, such as `cloudflared`.

So both forms would still avoid publishing directly to the real machine, but the loopback form is stricter and cleaner. It follows least exposure: `cloudflared` can reach the database, while the database is not unnecessarily listening on the DinD host container's other interfaces.

## What `start_e2e.sh` Does

`start_e2e.sh` is the full experiment entrypoint. By default it:

1. generates `.runtime/dind.env` and `.runtime/public_hosts.json`;
2. validates the Compose file;
3. builds and starts `dind-host-container`;
4. waits for the DinD-host topology to become ready;
5. runs a host-side experiment for about 30 seconds;
6. simulates:
   - a DBeaver-style PostgreSQL client;
   - an external Neo4j Bolt client;
   - a direct Neo4j HTTPS consumer;
7. writes raw artifacts under `_logs/raw/`;
8. appends `_logs/RUNLOG.md`;
9. writes `_logs/YYMMDD_HHMMSS_summary.md`;
10. stops the Compose stack unless `--keep-up` is used.

## What `start_host.sh` Does

`start_host.sh` is the host-testing entrypoint. It:

1. generates the separated runtime files;
2. validates and starts the DinD stack;
3. waits for topology readiness;
4. starts the Python bridge in the foreground;
5. keeps the stack and the bridge alive until `Ctrl+C`;
6. stops both on exit.

This is the script to use when you want DBeaver on the real machine to connect through the Python bridge without also running the automated proof workload.

## Quick Start

```bash
./start_e2e.sh
```

## Host Testing

For direct host-side testing with DBeaver or another Bolt/PostgreSQL client:

```bash
./start_host.sh
```

That command keeps the stack and the foreground Python bridge running until you press `Ctrl+C`.

If you want the bridge to run immediate real PostgreSQL and Neo4j queries before it settles into the foreground:

```bash
./start_host.sh --verify
```

1. PostgreSQL / DBeaver pattern
  - The foreground bridge exposes a local PostgreSQL port on `127.0.0.1:55432` by default.
  - DBeaver can connect to that local port exactly like a normal PostgreSQL server.
  - Use database `tunnel_demo`, user `tunnel_demo`, password `tunnel-demo-postgres`, and disable SSL.
  - Do not point DBeaver directly at the public Cloudflare hostname expecting a native PostgreSQL socket; the public side is a WebSocket carrier, so the local bridge is the supported path in this repository.

2. Neo4j Bolt pattern
   - The foreground bridge exposes a local Bolt port on `127.0.0.1:57687` by default.
   - Any Bolt-capable application can connect to that local port with the same Neo4j credentials.
   - Do not point a Bolt driver directly at the public Cloudflare hostname; the Python bridge layer is required.

The actual forwarded local ports are recorded in `_logs/raw/*_experiment_report.json`.

## Logs

- `_logs/raw/`
  - disposable runtime artifacts such as raw `.log` files and machine-readable `.json` reports
- `_logs/RUNLOG.md`
  - appended end-to-end experiment history
- `_logs/YYMMDD_HHMMSS_summary.md`
  - tracked iteration summary for the verified implementation run

## Notes

- Tunnel tokens remain in `tunnels.json` and are never copied into tracked markdown.
- Tunnel 4 is intentionally reserved and is not used by the automated experiment.
- `docker compose ps` may show `2375-2376/tcp` because the base `docker:dind` image exposes those ports as image metadata. The real no-host-publish check is `docker inspect ... .NetworkSettings.Ports`, which stays empty in this demo.
- Cloudflare references used for the transport model:
  - Tunnel setup: https://developers.cloudflare.com/tunnel/setup/
  - Protocol support: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/
