# `src/utils`

## Purpose

This component contains the operational support code around the actual proof
run.

If `src/bridge` is the transport layer and `src/simulators` is the service
proof layer, `src/utils` is everything that makes the system runnable and
operable:

- runtime file generation
- dependency loading
- Docker polling
- topology loading
- smoke-test and markdown reporting helpers

## Why This Is Separate

These utilities are deliberately not mixed into the bridge or simulator
modules.

That separation keeps the boundaries clear:

- `src/bridge`
  - transport conversion only
- `src/simulators`
  - real service-level proof operations only
- `src/utils`
  - runtime preparation, operator tooling, validation, and report helpers

## Files By Role

### Runtime generation and stack readiness

- `prepare_runtime.py`
  - reads `tunnels.json`
  - writes:
    - `.runtime/dind.env`
    - `.runtime/public_hosts.json`
  - prints non-secret derived runtime info

- `wait_for_stack.py`
  - waits for `_logs/raw/<RUN_TS>_topology_ready.json`
  - prints progress while the DinD host is pulling images and starting services

### Report and log helpers

- `smoke_test.py`
  - validates the machine-readable experiment report

- `append_runlog.py`
  - appends a compact markdown entry to `_logs/RUNLOG.md`

- `write_summary.py`
  - writes `_logs/<RUN_TS>_summary.md`

### Small shared helpers

- `demo_config.py`
  - central non-secret constants

- `dependencies.py`
  - lazy imports for optional runtime dependencies

- `docker_runtime.py`
  - top-level Docker state helpers

- `envfiles.py`
  - public-host runtime-file loading

- `files.py`
  - atomic JSON writing

- `topology.py`
  - topology snapshot loading with fallback defaults

## Detailed Module Notes

### `prepare_runtime.py`

#### Why it exists

The repository needs two different views of runtime state:

- DinD/server-side
  - includes tunnel tokens
- host/client-side
  - must not include tunnel tokens

`prepare_runtime.py` is the boundary that creates those separate runtime files.

#### What it writes

- `.runtime/dind.env`
  - for Docker Compose and the DinD host
- `.runtime/public_hosts.json`
  - for host-side Python code

#### How to use

```bash
python3 src/utils/prepare_runtime.py
```

Run it before:

- `docker compose up --build -d`
- `./start_e2e.sh`
- `./start_host.sh`

### `wait_for_stack.py`

#### Why it exists

Neo4j startup and first-time image pulls are slower than the host-side Python
scripts. This helper prevents the experiment from starting before the DinD host
has finished orchestrating its child services.

#### How to use

```bash
python3 src/utils/wait_for_stack.py --run-ts 260320_221836
```

#### Success condition

It returns success only when the orchestrator's topology marker says:

- `all_ready == true`

### Manual bridge workflow

The manual localhost bridge workflow is owned by `src/bridge`, not by
`src/utils`.

Use:

```bash
.venv/bin/python src/bridge/start_local_bridges.py
```

`src/utils` still supports that flow indirectly by providing:

- `demo_config.py`
  - shared non-secret settings such as default bridge ports and credentials
- `envfiles.py`
  - loading of `.runtime/public_hosts.json`
- `dependencies.py`
  - lazy imports used by the bridge CLI and verification helpers

### `smoke_test.py`

#### Why it exists

The experiment always writes a machine-readable JSON report. `smoke_test.py`
turns that report into an explicit pass/fail gate.

It checks:

- correct `run_id`
- `all_ok == true`
- at least three cycles completed
- PostgreSQL tunnel path succeeded
- Neo4j Bolt tunnel path succeeded
- Neo4j HTTPS path succeeded
- top-level published ports are empty

#### How to use

```bash
python3 src/utils/smoke_test.py --run-ts 260320_221626
```

### `append_runlog.py`

#### Why it exists

This keeps a readable chronological history of verified runs in
`_logs/RUNLOG.md`.

#### How to use

```bash
python3 src/utils/append_runlog.py --run-ts 260320_221626
```

### `write_summary.py`

#### Why it exists

This writes the short tracked markdown snapshot for one run:

```text
_logs/<RUN_TS>_summary.md
```

#### How to use

```bash
python3 src/utils/write_summary.py --run-ts 260320_221626
```

### `demo_config.py`

This is the single source of truth for non-secret demo constants such as:

- demo usernames and passwords
- default local bridge ports
- default experiment duration and cycle interval

Host-side code uses this file so it does not need to read DinD-only secret
runtime files.

### `dependencies.py`

This module uses lazy imports so simple paths such as `--help` do not require
all third-party runtime libraries to be installed at import time.

That is why modules call functions such as:

- `get_psycopg_module()`
- `get_requests_module()`
- `get_websocket_module()`
- `get_graph_database_class()`

instead of importing those dependencies at top level.

### `docker_runtime.py`

This module is a small wrapper around `docker ps` and `docker inspect`.

It is used to:

- report the top-level container status during readiness waits
- prove that the top-level DinD container has not published real host ports

### `envfiles.py`

This module parses `.runtime/public_hosts.json` into a plain Python mapping.

It is intentionally tiny because the host-side code should only see the public
hostnames, not the DinD token file.

### `files.py`

This module writes JSON files atomically:

- write to temporary file
- replace target file

That prevents later readers from seeing half-written report files.

### `topology.py`

This module loads the orchestrator's aggregated topology snapshot and falls
back to the expected static demo topology if the file is missing or malformed.

That keeps reporting resilient while still preferring the actual discovered
service set when available.

## Typical Flows

### Automated end-to-end flow

1. `prepare_runtime.py`
2. outer shell wrapper starts Compose
3. `wait_for_stack.py`
4. `src/experiment_runner.py`
5. `smoke_test.py`
6. `append_runlog.py`
7. `write_summary.py`

### Manual host testing flow

1. `prepare_runtime.py`
2. start outer stack
3. `wait_for_stack.py`
4. `src/bridge/start_local_bridges.py`
5. connect DBeaver or Bolt clients to localhost

## What This Component Does Not Do

It does not:

- run `cloudflared` on the client side
- own the TCP-to-WebSocket byte transport
- implement service-specific SQL or Cypher proof logic

Those concerns belong to `src/bridge` and `src/simulators`.
