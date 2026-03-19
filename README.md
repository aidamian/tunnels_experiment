# tunnels_experiment

This repository demonstrates a double-nested access pattern:

1. A single top-level Docker-in-Docker host container runs all outbound Cloudflare Tunnel connectors.
2. Inside that container, one nested DinD child runs Neo4j and another nested DinD child runs PostgreSQL.
3. A Python script runs directly on the real machine and reaches those databases only through the public tunnel hostnames.

The critical rule is simple: the top-level DinD host container publishes no service ports to the real machine. The only path out is Cloudflare Tunnel.

## Topology

```text
Real Machine
|
|-- start.sh
|-- scripts/run_experiment.py
|    |-- HTTPS -> Neo4j public hostname
|    |-- local TCP bridge -> Neo4j Bolt public hostname
|    |-- local TCP bridge -> PostgreSQL public hostname
|
`-- docker compose
     `-- dind-host-container
          |-- cloudflared tunnel run -> Neo4j HTTPS
          |-- cloudflared tunnel run -> Neo4j Bolt
          |-- cloudflared tunnel run -> PostgreSQL
          |-- neo4j-dind
          |    `-- neo4j-demo
          `-- postgres-dind
               `-- postgres-demo
```

## Why It Works

Step by step:

1. `dind-host-container` starts a private nested Docker daemon.
2. That daemon runs two DinD child containers, one per database family.
3. Each DinD child starts its own inner Docker daemon and then its own database container.
4. The inner database container publishes its port only to its immediate DinD parent boundary.
5. The top-level `dind-host-container` reaches those child-DinD-published ports over the nested private network.
6. `cloudflared tunnel run` inside `dind-host-container` opens outbound-only connections to Cloudflare and maps the public hostnames to those private origins.
7. The real machine never receives a direct port publish from the top-level Compose service.
8. For TCP protocols, the host-side Python bridge opens ordinary local sockets so tools such as DBeaver or Neo4j Bolt applications can connect as if the services were local.

## What `start.sh` Does

`start.sh` is the full experiment entrypoint. By default it:

1. generates `.runtime/tunnels.env`;
2. validates the Compose file;
3. builds and starts `dind-host-container`;
4. waits for the nested topology to become ready;
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

2. Neo4j Bolt pattern
   - The automated Python bridge binds a local Bolt port on `127.0.0.1`.
   - Any Bolt-capable application can connect to that local port with the same Neo4j credentials.

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
