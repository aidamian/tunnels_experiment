# DOCUMENTATION.md

## Status
- Phase: verified working demo
- Current objective: keep the single-top-level DinD host topology stable and reproducible

## Intended Architecture
- Top-level Compose service:
  - `dind-host-container`
- Nested DinD child containers started by `dind-host-container`:
  - `neo4j-dind`
  - `postgres-dind`
- Inner database containers:
  - `neo4j-demo`
  - `postgres-demo`
- Host-side consumer:
  - `scripts/run_experiment.py`

## Key Rules
- No top-level Compose port is published to the real machine.
- All outbound service exposure happens through `cloudflared tunnel run` inside `dind-host-container`.
- The real machine reaches PostgreSQL and Neo4j Bolt through host-side local TCP bridges opened by `scripts/run_experiment.py`.
- The real machine reaches Neo4j HTTPS directly through the public tunnel hostname.

## Expected Workflow
1. `python3 scripts/prepare_runtime.py`
2. `./start.sh`
3. Inspect `_logs/raw/` for raw artifacts.
4. Inspect `_logs/RUNLOG.md` for the appended end-to-end result.

## Verified Run
- Verified run identifier: `260319_141702`
- Verified outcome:
  - `./start.sh` completed end to end and then stopped the stack automatically;
  - the top-level `dind-host-container` remained healthy;
  - the top-level container published no host port bindings;
  - Neo4j HTTPS succeeded over `c74d8a4e03e6.ratio1.link`;
  - Neo4j Bolt succeeded through the host-side local bridge on `127.0.0.1:17687`;
  - PostgreSQL succeeded through the host-side local bridge on `127.0.0.1:15432`;
  - the host-side experiment completed four write/read cycles over about 30 seconds.
