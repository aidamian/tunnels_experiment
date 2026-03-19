# REVIEW.md

## Critic Checklist
Run this checklist after each milestone and before declaring the demo complete.

### Secrets
- No tunnel token appears in tracked files, markdown summaries, or user-facing command summaries.
- `.runtime/` remains ignored.
- `_logs/raw/` contains runtime output only.

### Topology
- Compose defines exactly one top-level service: `dind-host-container`.
- `dind-host-container` publishes no ports to the real machine.
- Neo4j runs inside `neo4j-dind` as an inner child container.
- PostgreSQL runs inside `postgres-dind` as an inner child container.
- `cloudflared tunnel run` exists only inside `dind-host-container`.
- The active Python experiment runs directly on the real machine.

### Tunnel mapping
- tunnel 1 -> Neo4j HTTPS
- tunnel 2 -> Neo4j Bolt/TCP
- tunnel 3 -> PostgreSQL TCP
- tunnel 4 -> reserved and unused by the automated experiment

### Functional proof
- Neo4j HTTPS is verified over the public hostname.
- Neo4j Bolt is verified through the host-side local TCP bridge and a real driver query.
- PostgreSQL is verified through the host-side local TCP bridge and a real SQL query.
- The PostgreSQL proof inserts new timestamped rows and reads them back.
- The Neo4j proof creates new timestamped graph data and reads it back.
- The latest generated report shows `all_ok: true`.

### Operational quality
- `docker compose config -q` passes.
- `./start.sh` can drive the full run.
- `_logs/raw/` contains separated runtime artifacts.
- `_logs/RUNLOG.md` contains an end-to-end entry for the verified run.
- `DOCUMENTATION.md` and `README.md` match the actual verified topology.
