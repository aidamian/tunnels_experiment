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
|-- start.sh
|-- scripts/sre/run_experiment.py
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

The host-side Python code now has a clearer split inside `scripts/`:

- `scripts/sre/`
  - primary operator entrypoints used by `start.sh` and `Makefile`
- `scripts/src/tunnels_experiment/utils/`
  - shared env, file, Docker, dependency, and topology helpers
- `scripts/src/tunnels_experiment/bridges/`
  - the Cloudflare TCP-over-WebSocket bridge implementation
- `scripts/src/tunnels_experiment/checks/`
  - separate PostgreSQL, Neo4j Bolt, and Neo4j HTTPS proof logic
- `scripts/src/tunnels_experiment/experiment/`
  - the top-level experiment coordinator
- `scripts/*.py`
  - compatibility wrappers that preserve the historical flat commands

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
- That is why the host-side experiment runner in `scripts/src/tunnels_experiment/experiment/runner.py` creates local TCP listeners on `127.0.0.1` and relays those byte streams to `wss://<public-hostname>`.
  Local clients still speak ordinary Bolt or PostgreSQL to the bridge, while the bridge handles the WebSocket carrier required by Cloudflare's TCP mode.

So the public hostname is a Cloudflare HTTPS/TLS endpoint, but the payload inside that connection can still be a raw TCP application such as Bolt or PostgreSQL.

In the official Cloudflare model, non-HTTP applications normally use a client-side `cloudflared` helper. This repository makes that transport explicit by implementing the same bridge idea directly in Python for the host-side proof workload.

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

## What `start.sh` Does

`start.sh` is the full experiment entrypoint. By default it:

1. generates `.runtime/tunnels.env`;
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

## Quick Start

```bash
./start.sh
```

## Manual Verification

If you want the stack to stay up after the automated run:

```bash
./start.sh --keep-up --duration-seconds 120
```

While that run is active:

1. PostgreSQL / DBeaver pattern
   - The automated Python bridge binds a local PostgreSQL port on `127.0.0.1`.
   - DBeaver can connect to that local port exactly like a normal PostgreSQL server.
   - Use the same database name, username, and password shown in `.runtime/tunnels.env`.
   - Do not point DBeaver directly at the public Cloudflare hostname expecting a native PostgreSQL socket; the public side is a WebSocket carrier, so the local bridge is the supported path in this repository.

2. Neo4j Bolt pattern
   - The automated Python bridge binds a local Bolt port on `127.0.0.1`.
   - Any Bolt-capable application can connect to that local port with the same Neo4j credentials.
   - Do not point a Bolt driver directly at the public Cloudflare hostname unless you also provide the client-side WebSocket/TCP bridge layer.

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
  - Arbitrary TCP client-side pattern: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/
