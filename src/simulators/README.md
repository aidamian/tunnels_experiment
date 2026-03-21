# `src/simulators`

## Purpose

This component contains the proof workloads for each service path verified by
the host-side experiment.

The key idea is simple:

- `src/experiment_runner.py` decides when to run a proof cycle
- `src/bridge` provides local TCP bridge ports where needed
- `src/simulators` performs the actual service-specific read and write actions

That keeps protocol-specific code out of the top-level coordinator.

## Files

- `postgres.py`
  - PostgreSQL write/read proof through the host-side local TCP bridge
  - also contains the lightweight manual-bridge connectivity check
- `neo4j_bolt.py`
  - Neo4j Bolt write/read proof through the host-side local TCP bridge
  - also contains the lightweight manual-bridge connectivity check
- `neo4j_https.py`
  - Neo4j HTTP API read proof directly over the public HTTPS hostname

## Why This Is Separate

These modules are split out because each path proves something different:

- PostgreSQL proves raw TCP database traffic works through the tunnel path
- Neo4j Bolt proves raw Bolt traffic works through the tunnel path
- Neo4j HTTPS proves the public HTTP path works without a local TCP bridge

If all of that logic lived in `experiment_runner.py`, the coordinator would
also need to own SQL, Cypher, HTTP payloads, row parsing, and driver-specific
details. Keeping those concerns separate makes the orchestration simpler and
the proof behavior easier to reason about.

## Design Rules

Each simulator function:

- accepts plain inputs from the coordinator
  - `run_id`
  - `cycle`
  - `proof`
  - local port or public host as needed
- performs a real client operation
  - no mocks
  - no shortcut access to the database container
- returns a structured dictionary that can go directly into the experiment
  report

That report-first design is why the functions return dictionaries rather than
printing text.

## `postgres.py`

### What it proves

`run_postgres_cycle()` proves that a PostgreSQL client can:

1. connect to the localhost bridge port
2. insert a proof row
3. read the run's rows back

### How it works

- imports `psycopg` lazily through `utils.dependencies`
- connects to:
  - host: `127.0.0.1`
  - port: provided by the caller
- uses demo credentials from `utils.demo_config`
- writes into `tunnel_run_events`
- uses `ON CONFLICT` to keep repeated runs for the same `run_id/cycle` idempotent

### Function

```python
run_postgres_cycle(run_id: str, cycle: int, proof: str, local_port: int) -> dict[str, Any]
```

Manual bridge smoke helper:

```python
verify_postgres_bridge(local_port: int) -> dict[str, Any]
```

### Example

```python
from simulators.postgres import run_postgres_cycle

result = run_postgres_cycle(
  run_id="demo_run",
  cycle=1,
  proof="demo_run-cycle-1",
  local_port=15432,
)
print(result["rows_for_run"])
```

## `neo4j_bolt.py`

### What it proves

`run_neo4j_bolt_cycle()` proves that a Bolt-capable application can:

1. connect to the localhost Bolt bridge
2. write graph data over Bolt
3. read the run's events back over Bolt

### How it works

- imports Neo4j's `GraphDatabase` lazily
- connects to `bolt://127.0.0.1:<port>`
- writes:
  - `ExperimentRun`
  - `ExperimentEvent`
  - relationships from the simulated external Bolt client
- reads the run's event list back in cycle order

### Function

```python
run_neo4j_bolt_cycle(run_id: str, cycle: int, proof: str, local_port: int) -> dict[str, Any]
```

Manual bridge smoke helper:

```python
verify_neo4j_bolt_bridge(local_port: int) -> dict[str, Any]
```

### Example

```python
from simulators.neo4j_bolt import run_neo4j_bolt_cycle

result = run_neo4j_bolt_cycle(
  run_id="demo_run",
  cycle=1,
  proof="demo_run-cycle-1",
  local_port=17687,
)
print(result["events_for_run"])
```

## `neo4j_https.py`

### What it proves

`run_neo4j_https_read()` proves that the Neo4j HTTP API is reachable over the
public HTTPS tunnel hostname without any local TCP bridge.

This path intentionally differs from PostgreSQL and Bolt:

- it uses `https://<public-hostname>`
- it talks to Neo4j's HTTP transaction endpoint directly
- it proves the HTTP path independently of the Bolt path

### How it works

- imports `requests` lazily
- POSTs a Cypher transaction payload to `/db/neo4j/tx/commit`
- authenticates with the demo Neo4j credentials
- parses the result rows into the same report-friendly dictionary shape used by
  the other simulators

### Function

```python
run_neo4j_https_read(run_id: str, public_http_host: str) -> dict[str, Any]
```

### Example

```python
from simulators.neo4j_https import run_neo4j_https_read

result = run_neo4j_https_read(
  run_id="demo_run",
  public_http_host="c74d8a4e03e6.ratio1.link",
)
print(result["endpoint"])
```

## How The Coordinator Uses These Modules

The normal call flow is:

1. `experiment_runner.py` starts the local PostgreSQL and Neo4j Bolt bridges
2. for each cycle it creates a unique proof string
3. it calls:
   - `run_postgres_cycle(...)`
   - `run_neo4j_bolt_cycle(...)`
   - `run_neo4j_https_read(...)`
4. it merges those results into the final report

That division lets the coordinator stay focused on timing, lifecycle, and
report writing rather than protocol details.

## How To Use

These modules are not CLIs. They are internal library code.

The normal supported usage is:

- via `src/experiment_runner.py`
- via `src/bridge/start_local_bridges.py --verify` for the lighter manual
  connectivity checks

If you call them directly:

- make sure the relevant tunnel path is already up
- make sure the required local bridge exists for PostgreSQL or Bolt
- make sure `requirements-host.txt` is installed in the Python environment

## What This Component Does Not Do

It does not:

- start bridges
- read `.runtime/public_hosts.json`
- wait for the DinD stack
- write reports to disk
- decide when a run starts or stops

Those concerns belong to `src/bridge`, `src/utils`, and
`src/experiment_runner.py`.
