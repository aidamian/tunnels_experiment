# IMPLEMENTATION.md

## Role
This file is the builder runbook. `PLANNING.md` is the architecture source of truth.

## Operating Rules
- Complete one milestone at a time.
- Validate each milestone before moving on.
- Keep tunnel secrets out of tracked files and command summaries.
- Prefer tracked scripts and Docker files over ad hoc shell history.
- Treat `_logs/raw/` as disposable runtime output.
- Append `_logs/RUNLOG.md` only after a full end-to-end run.

## Build Order
1. Runtime preparation
   - secret-safe env generation from `tunnels.json`
   - `_logs/raw/` scaffolding
2. Top-level DinD host
   - single-service Compose
   - no published host ports
   - health marker for DinD-host topology readiness
   - in-image `entrypoint.sh`
   - in-image `orchestrator.sh`
   - in-image `servers/neo4j.sh` and `servers/pgsql.sh`
3. Direct child service containers
   - `neo4j-demo`
   - `postgres-demo`
   - seed data
   - outbound `cloudflared tunnel run` processes only in the top-level host
4. Host-side experiment
   - host-side TCP bridge listeners for PostgreSQL and Neo4j Bolt
   - PostgreSQL write/read proof
   - Neo4j Bolt write/read proof
   - Neo4j HTTPS read proof
5. Verification and documentation
   - `start.sh`
   - `src/utils/smoke_test.py`
   - optional manual Python bridge helper for DBeaver and Bolt
   - `DOCUMENTATION.md`
   - `_logs/RUNLOG.md`
   - `_logs/YYMMDD_HHMMSS_summary.md`

## Validation Discipline
- Run `python3 src/utils/prepare_runtime.py` before Compose commands.
- Use `docker compose config -q` to validate Compose without printing secret-expanded config.
- Use `./start.sh` for the real integration path.
- Use `python3 src/utils/smoke_test.py --run-ts ...` for report validation when debugging.

## Scope Limits
- Do not publish any service port from the top-level DinD host container to the real machine.
- Do not run `cloudflared tunnel run` anywhere except the top-level DinD host container.
- Do not move the active Python consumer back into a container.
- Do not pretend PostgreSQL or Bolt are HTTP services.
- Do not reintroduce extra DinD child containers unless `PLANNING.md` changes first.
