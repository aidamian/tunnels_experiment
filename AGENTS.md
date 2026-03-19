# AGENTS.md

## Purpose
This repository exists to demonstrate Cloudflare Tunnel access to services running inside a single Docker-in-Docker host, with a Python consumer on the real machine that proves those tunnels work end to end.

The intended steady-state topology is:
- `dind-host-container`: the single top-level Docker-in-Docker (DinD) container.
- `neo4j-demo`: a direct child container started by the DinD host and exposed through two tunnels: HTTPS and Bolt/TCP.
- `postgres-demo`: a direct child container started by the DinD host and exposed through one TCP tunnel.
- `scripts/run_experiment.py`: the host-side Python consumer that reaches those services through the public tunnel hostnames and host-side local TCP bridges.

## Durable Memory
Read these files before making non-trivial changes:
- `PLANNING.md`: project spec, architecture, milestones, acceptance criteria, validation commands.
- `IMPLEMENTATION.md`: builder runbook.
- `REVIEW.md`: critic checklist.
- `DOCUMENTATION.md`: live status, decisions, run instructions, and demo notes.
- `_logs/YYMMDD_HHMMSS_*.md`: timestamped iteration summaries.

## Builder-Critic Loop
1. Builder pass: read `PLANNING.md` and `IMPLEMENTATION.md`, then complete exactly one milestone at a time.
2. Validation pass: run the milestone commands from `PLANNING.md`.
3. Critic pass: use `REVIEW.md` to look for regressions, secret leaks, missing verification, and drift from the requested topology.
4. Documentation pass: update `DOCUMENTATION.md` and append a timestamped summary under `_logs/`.
5. Only then move to the next milestone.

## Guardrails
- `tunnels.json` contains live tunnel tokens. Never print, commit, or copy those tokens into tracked files.
- Use `scripts/prepare_runtime.py` to generate `.runtime/tunnels.env`. Treat `.runtime/` as disposable runtime state.
- The tunnel-role mapping is fixed unless `PLANNING.md` is explicitly updated:
  - tunnel 1: Neo4j HTTPS
  - tunnel 2: Neo4j Bolt/TCP
  - tunnel 3: PostgreSQL TCP
  - tunnel 4: reserved and unused by the automated experiment
- Stop and fix immediately if a validation command fails. Do not continue with a broken milestone.
- Keep orchestration reproducible with `docker compose`, scripts, and tracked markdown. Avoid relying on undocumented one-off container state.
- Prefer official images and primary-source documentation for Cloudflare Tunnel, Docker, Neo4j, PostgreSQL, and Codex workflow behavior.
- Keep `_logs/*.md` summaries tracked and `_logs/*.log` runtime logs untracked.

## Definition Of Done
The project is only complete when all of the following hold:
- `python3 scripts/prepare_runtime.py` succeeds against the local `tunnels.json`.
- `docker compose up --build -d` brings up the single top-level `dind-host-container`.
- The host-side experiment can prove all of these paths work:
  - Neo4j over public HTTPS
  - Neo4j over Bolt through the host-side local TCP bridge
  - PostgreSQL over TCP through the host-side local TCP bridge
- The top-level Compose service publishes no ports to the real machine.
- `DOCUMENTATION.md` and the current timestamped `_logs/*.md` summary reflect the final verified state.
