# PLAN.md

## Goal
Refactor the repository so client-side and server-side artifacts live in separate worlds:

- `servers/`
  - Docker Compose, DinD image files, `tunnels.json`, server runtime files, and server raw logs
- `clients/`
  - `services.json`, client Python code, client runtime/config files, client raw logs, and client Python environment inputs

The separation rule is strict:

- client code must not import from `servers/`
- server code must not import from `clients/`
- client code must not read files generated under `servers/`
- server code must not read files generated under `clients/`
- only root-level orchestration/docs may know both paths, and they should pass values through CLI arguments or process environment rather than shared files
- no new shared runtime directories may be introduced at repo root

## Refactor Principles
1. Treat `services.json` as the client-owned service catalog.
2. Remove hardcoded bridge service definitions from the client bridge layer.
3. Keep the fixed tunnel-role mapping on the server side unless `IMPLEMENTATION.md` is intentionally changed.
4. Preserve the verified topology:
   - one top-level `dind-host-container`
   - Neo4j HTTPS through a public hostname
   - Neo4j Bolt through a client-side local TCP bridge
   - PostgreSQL through a client-side local TCP bridge
5. Keep secret material only on the server side:
   - `servers/tunnels.json`
   - `servers/.runtime/dind.env`
6. Keep structured artifacts ANSI-free:
   - JSON, Markdown, env files stay plain text
   - ANSI color is for human-facing console and `.log` streams only

## Target Layout
Root stays for repo-level coordination and documentation:

```text
.
|-- PLAN.md
|-- IMPLEMENTATION.md
|-- README.md
|-- AGENTS.md
|-- _logs/
|   |-- RUNLOG.md
|   `-- YYMMDD_HHMMSS_summary.md
|-- start_e2e.sh
|-- start_host.sh
|-- Makefile
|-- clients/
|   |-- services.json
|   |-- requirements.txt
|   |-- .venv/                  # ignored
|   |-- _logs/raw/              # ignored except .gitkeep
|   `-- src/
|-- servers/
|   |-- docker-compose.yml
|   |-- tunnels.json            # ignored
|   |-- .runtime/               # ignored
|   |-- _logs/raw/              # ignored except .gitkeep
|   `-- docker/
```

Repo-level `_logs/` remains documentation-only so the two worlds do not share runtime folders.
Repo-root `.venv/`, `.runtime/`, and raw runtime logs should disappear from the active workflow.

## Client Contract Changes
`clients/services.json` becomes the only client-side service inventory. The client bridge and experiment code will read service metadata from this file instead of hardcoding bridge specifications in Python.

Planned client schema shape:

```json
[
  {
    "key": "neo4j_https",
    "service": "Neo4J HTTPS Access",
    "type": "https",
    "url": "https://example.com"
  },
  {
    "key": "neo4j_bolt",
    "service": "Neo4J Bolt",
    "type": "bolt",
    "url": "bolt-public-host.example.com",
    "bridge": {
      "local_host": "127.0.0.1",
      "local_port": 57687
    }
  },
  {
    "key": "postgres",
    "service": "PostgreSQL",
    "type": "tcp",
    "url": "postgres-public-host.example.com",
    "bridge": {
      "local_host": "127.0.0.1",
      "local_port": 55432
    }
  }
]
```

Notes:

- `key` gives the client code a stable identifier without hardcoding positional assumptions.
- `bridge` appears only for TCP-over-WebSocket services that require a local bridge.
- HTTPS stays direct and does not need a bridge section.
- the `bridge.local_port` value becomes the client-owned default for both automated and manual bridge startup, with CLI overrides allowed for manual workflows
- If needed, the experiment runner can keep client credentials in client-owned config code, but not in any shared file read by the server.

## Server Contract Changes
Server runtime generation stays server-owned:

- move `src/utils/prepare_runtime.py` to `servers/src/utils/prepare_runtime.py`
- move `src/utils/wait_for_stack.py` to `servers/src/utils/wait_for_stack.py`
- move Docker assets under `servers/docker/`
- move `docker-compose.yml` to `servers/docker-compose.yml`
- keep DinD runtime env under `servers/.runtime/dind.env`
- keep server raw runtime logs under `servers/_logs/raw/`
- ensure the Compose build context is `servers/` so the DinD image build does not rely on repo-root or client-side files

The client will no longer read:

- `servers/.runtime/public_hosts.json`
- `servers/_logs/raw/<RUN_TS>_topology_ready.json`

If a root-level workflow needs server readiness or `RUN_TS`, it can read the server-owned files and pass values into client commands as arguments.

## Logging And ANSI Color Plan
Introduce explicit world-specific logging helpers.

Root shell entrypoints:

- add a small ANSI palette helper to `start_e2e.sh` and `start_host.sh`
- use one color for high-level step banners, one for success, one for warnings/errors

Server shell logs:

- extend `servers/docker/dind/lib/common.sh` with color-aware `log_with_scope`
- assign stable colors by scope:
  - `entrypoint`: cyan
  - `orchestrator`: blue
  - `neo4j`: green
  - `pgsql`: yellow
  - failures: red

Client Python logs:

- add a client logging helper for colorized line output
- assign stable colors by concern:
  - experiment coordinator: cyan
  - postgres bridge/proof: green
  - neo4j bridge/proof: blue
  - verification/warnings: yellow
  - failures: red

Output rule:

- console output and raw `.log` streams may contain ANSI escapes
- JSON reports, Markdown summaries, and env/config files must remain plain text

## Execution Plan
1. Create the new directory skeleton under `clients/` and `servers/`, keeping root docs and orchestration files in place.
2. Move client-owned files:
   - host Python sources
   - `services.json`
   - `requirements-host.txt` -> `clients/requirements.txt`
   - client raw log directory
3. Move server-owned files:
   - Compose file
   - Dockerfiles and DinD scripts
   - server runtime helpers
   - server raw log directory
4. Refactor client imports and path resolution to use `clients/` locations only.
5. Replace hardcoded bridge specs with a `services.json` loader and typed client service model.
6. Remove client dependency on server-generated runtime files and topology logs.
7. Update root entrypoints and `Makefile` to invoke the new client/server paths without recreating root `.venv`, root `.runtime`, or root raw runtime logs.
8. Add ANSI-aware logging helpers in shell and Python.
9. Update docs:
   - `IMPLEMENTATION.md`
   - `README.md`
   - relevant per-directory READMEs if they remain useful
10. Append a new timestamped root `_logs/*_summary.md` reflecting the verified refactor.

## Separation Review Checklist
This checklist must be applied before execution and again after implementation:

1. Does any file under `clients/` read from `servers/.runtime`, `servers/_logs`, `servers/docker`, or `servers/tunnels.json`?
2. Does any file under `servers/` read from `clients/services.json`, `clients/_logs`, or client Python modules?
3. Are client bridge targets and local ports sourced from `clients/services.json` rather than hardcoded Python lists?
4. Are runtime logs split into `servers/_logs/raw/` and `clients/_logs/raw/`?
5. Are only repo-level docs still written under root `_logs/`?
6. Do root scripts coordinate the two worlds without turning root into a new shared runtime directory?
7. Is the DinD image build context restricted to `servers/`?
8. Do JSON and Markdown artifacts remain free of ANSI sequences?

## Validation Plan
Static checks:

- `bash -n start_e2e.sh start_host.sh`
- `docker compose -f servers/docker-compose.yml config -q`
- `python3 servers/src/utils/prepare_runtime.py`
- relevant `--help` checks for moved Python CLIs

Functional checks:

- `./start_e2e.sh --duration-seconds 1`
- `timeout -s INT 90 ./start_host.sh --verify`

Success conditions:

- top-level Compose still publishes no host ports
- client experiment still proves:
  - Neo4j over public HTTPS
  - Neo4j Bolt through the client bridge
  - PostgreSQL through the client bridge
- client and server runtime artifacts stay in their own directories
- repo-level docs match the new split

## Expected Iteration Loop
1. Write this plan.
2. Review it against the separation checklist and tighten weak points.
3. Execute the refactor.
4. Run validation.
5. Fix anything that violates the checklist or breaks validation.
6. Update docs and write the final iteration summary.
