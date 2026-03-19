# AGENTS.md

## Purpose
This repository exists to demonstrate Cloudflare Tunnel access to services running inside containerized environments, with a Python consumer that proves those tunnels work end to end.

The intended steady-state topology is:
- `master`: a top-level Docker-in-Docker (DinD) container that builds and runs the consumer app as a child container and exposes it through tunnel 4.
- `embedded-neo4j`: a top-level DinD container that runs Neo4j as a child container and exposes it through two tunnels: HTTPS and Bolt/TCP.
- `embedded-postgres`: a top-level DinD container that runs PostgreSQL as a child container and exposes it through one TCP tunnel.

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
  - tunnel 4: Consumer HTTP
- Stop and fix immediately if a validation command fails. Do not continue with a broken milestone.
- Keep orchestration reproducible with `docker compose`, scripts, and tracked markdown. Avoid relying on undocumented one-off container state.
- Prefer official images and primary-source documentation for Cloudflare Tunnel, Docker, Neo4j, PostgreSQL, and Codex workflow behavior.
- Keep `_logs/*.md` summaries tracked and `_logs/*.log` runtime logs untracked.

## Definition Of Done
The project is only complete when all of the following hold:
- `python3 scripts/prepare_runtime.py` succeeds against the local `tunnels.json`.
- `docker compose up --build -d` brings up the three top-level DinD containers.
- The consumer app can prove all of these paths work:
  - Neo4j over public HTTPS
  - Neo4j over Bolt through client-side `cloudflared access tcp`
  - PostgreSQL over TCP through client-side `cloudflared access tcp`
- The public consumer URL returns a healthy report for all three checks.
- `DOCUMENTATION.md` and the current timestamped `_logs/*.md` summary reflect the final verified state.
