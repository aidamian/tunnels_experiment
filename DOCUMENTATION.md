# DOCUMENTATION.md

## Status
- Phase: verified working demo
- Current objective: maintain the Python-only consumer demo across Neo4j HTTPS, Neo4j Bolt, and PostgreSQL TCP

## Architecture Snapshot
- Top-level DinD roles:
  - `master`
  - `embedded-neo4j`
  - `embedded-postgres`
- Child workloads:
  - `consumer-demo`
  - `neo4j-demo`
  - `postgres-demo`
- Consumer behavior:
  - `consumer-demo` is a Python script, not an HTTP app
  - it writes probe output to `_logs/`
  - it uses the published hostnames for Neo4j HTTPS, Neo4j Bolt, and PostgreSQL
  - tunnel 4 is reserved and not required for the consumer proof

## Runtime Workflow
1. `python3 scripts/prepare_runtime.py`
2. `docker compose up --build -d`
3. `python3 scripts/smoke_test.py`

The current verified run used timestamp prefix `260319_114855_`.

## Demo Workflow
1. Start the stack with `docker compose up --build -d`.
2. Run `python3 scripts/smoke_test.py`.
3. Review the generated consumer report under `_logs/`.
4. Confirm the report shows:
   - Neo4j HTTPS OK
   - Neo4j Bolt OK
   - PostgreSQL TCP OK

## Decisions
- PostgreSQL is demonstrated over a TCP tunnel, not HTTPS.
- The consumer no longer bundles `cloudflared`; it uses a Python implementation of the Cloudflare TCP-over-WebSocket client flow against the public hostnames.
- The master role records cluster snapshots from the two embedded DinD daemons so it acts as control/observability, not just a place to host the consumer.
- `master` waits internally for the worker Docker APIs before building and starting the consumer child container.
- Tunnel 4 is reserved for optional diagnostics and is not required for the consumer proof.

## Known Limits
- The demo is designed for correctness and clarity, not long-lived production hardening.
- Cloudflare `tcp://` published applications do not accept native raw Bolt or PostgreSQL handshakes directly on the public hostname. The consumer must speak the published WebSocket transport internally.

## Verified Outcome
- `docker compose up --build -d` left `master`, `embedded-neo4j`, and `embedded-postgres` healthy on the verified run.
- `python3 scripts/smoke_test.py` passed against `_logs/260319_114855_consumer_report.json`.
- The consumer image does not contain `cloudflared`.
- The consumer script verified all of these paths with real traffic:
  - Neo4j transactional HTTP over `https://c74d8a4e03e6.ratio1.link`
  - Neo4j Bolt over `99c7e7089d1b.ratio1.link`
  - PostgreSQL TCP over `60bf15690490.ratio1.link`
