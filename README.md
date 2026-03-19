# tunnels_experiment

Cloudflare Tunnel demo for nested container workloads.

The stack uses three top-level Docker-in-Docker containers:
- `master`: builds and runs the Python consumer app as a child container and exposes it through tunnel 4
- `embedded-neo4j`: runs Neo4j as a child container and exposes HTTPS and Bolt through tunnels 1 and 2
- `embedded-postgres`: runs PostgreSQL as a child container and exposes TCP through tunnel 3

Quick start:
1. `python3 scripts/prepare_runtime.py`
2. `docker compose up --build -d`
3. `python3 scripts/smoke_test.py`

The public consumer URL will report the live tunnel status for Neo4j HTTPS, Neo4j Bolt, and PostgreSQL TCP.
