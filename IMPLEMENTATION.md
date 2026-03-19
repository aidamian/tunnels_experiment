# IMPLEMENTATION.md

## Role
This file is the builder runbook. Treat `PLANNING.md` as the source of truth for architecture, milestones, and validation commands.

## Operating Rules
- Complete one milestone at a time.
- Keep diffs scoped to the active milestone.
- Prefer tracked scripts and Docker files over ad hoc shell history.
- Run the listed validation commands after each milestone.
- If validation fails, repair immediately before moving on.
- Update `DOCUMENTATION.md` and the active `_logs/*.md` summary after each meaningful milestone.

## Build Order
1. Runtime preparation
   - secret-safe env generation from `tunnels.json`
   - ignore disposable runtime files
2. DinD control plane
   - top-level Compose
   - shared DinD image
   - role startup script
3. Service workloads
   - Neo4j child container and seed data
   - PostgreSQL child container and seed data
   - Cloudflare tunnel processes
4. Consumer workload
   - Python app
   - Bolt/PostgreSQL TCP proxy helpers
   - public report endpoints
5. Verification and documentation
   - smoke tests
   - tracked summary

## Validation Discipline
- Run `python3 scripts/prepare_runtime.py` before Compose commands.
- Use `docker compose config` to validate configuration before first boot.
- Use `docker compose up --build -d` for real integration testing.
- Use `python3 scripts/smoke_test.py` as the final public-path verification.

## Scope Limits
- Do not commit tunnel tokens or generated env files.
- Do not convert PostgreSQL into an HTTP service. It must remain a TCP tunnel demo.
- Do not replace the three top-level DinD architecture with direct top-level service containers.
