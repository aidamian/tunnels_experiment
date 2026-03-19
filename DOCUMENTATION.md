# DOCUMENTATION.md

## Status
- Phase: verified working demo
- Current objective: maintain the working public demo across Neo4j HTTPS, Neo4j Bolt, PostgreSQL TCP, and the public consumer report

## Architecture Snapshot
- Top-level DinD roles:
  - `master`
  - `embedded-neo4j`
  - `embedded-postgres`
- Child workloads:
  - `consumer-demo`
  - `neo4j-demo`
  - `postgres-demo`

## Runtime Workflow
1. `python3 scripts/prepare_runtime.py`
2. `docker compose up --build -d`
3. `python3 scripts/smoke_test.py`

The clean verification run used timestamp prefix `260319_102937_`.

## Demo Workflow
1. Open the public consumer URL from the generated runtime mapping.
2. Review the live `/report` output or the HTML summary at `/`.
3. Confirm the report shows:
   - Neo4j HTTPS OK
   - Neo4j Bolt OK
   - PostgreSQL TCP OK

## Decisions
- PostgreSQL is demonstrated over a TCP tunnel, not HTTPS.
- The consumer uses short-lived client-side `cloudflared access tcp` processes for Bolt and PostgreSQL so the proof uses the documented client path without relying on separate sidecars.
- The master role also records cluster snapshots from the two embedded DinD daemons so it acts as control/observability, not just a place to host the consumer tunnel.
- `master` no longer waits on Compose health-gated dependencies; instead, it starts alongside the workers and waits internally for their Docker APIs. This makes `docker compose up --build -d` converge reliably.
- The smoke test sends a `curl`-like user agent because the public consumer hostname returned `403` to Python's default `urllib` user agent.

## Known Limits
- The demo is designed for correctness and clarity, not long-lived production hardening.
- Non-HTTP Cloudflare published applications are best for short-lived or moderate-lived connections; this demo intentionally uses short validation queries.

## Verified Outcome
- `docker compose up --build -d` now leaves `master`, `embedded-neo4j`, and `embedded-postgres` healthy on a clean restart.
- `https://98c70737f05f.ratio1.link/report` returned `all_ok: true` on the final verification run.
- The consumer app verified all of these paths with real traffic:
  - Neo4j transactional HTTP over the public HTTPS hostname
  - Neo4j Bolt via client-side `cloudflared access tcp`
  - PostgreSQL via client-side `cloudflared access tcp`
