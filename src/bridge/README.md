# `src/bridge`

## Purpose

This component contains the transport adapter that makes Cloudflare-published
TCP services usable from normal local client tools.

In this repository, PostgreSQL and Neo4j Bolt are not exposed as native public
database sockets. Cloudflare carries those TCP streams over a WebSocket-based
edge transport. The bridge hides that detail and exposes ordinary localhost TCP
ports instead.

Without this component:

- DBeaver could not speak directly to the PostgreSQL tunnel FQDN as if it were
  a native PostgreSQL socket.
- Neo4j Bolt clients could not speak directly to the Bolt tunnel FQDN as if it
  were a native Bolt socket.
- the host-side experiment would have no clean way to simulate real client
  behavior.

## Files

- `universal.py`
  - reusable TCP-to-WebSocket bridge implementation
  - no product-specific PostgreSQL or Neo4j logic
- `local_bridges.py`
  - bridge-specific helper module for manual bridge specs and runtime host loading
- `start_local_bridges.py`
  - operator-facing manual bridge CLI

## How It Works

The main abstraction is `UniversalBridgeServer`.

It does four things:

1. binds a localhost TCP port such as `127.0.0.1:15432`
2. accepts ordinary local TCP clients
3. opens a `wss://<public-hostname>` connection to the Cloudflare TCP app
4. relays bytes in both directions

The data path is:

```text
local client
-> localhost TCP socket
-> UniversalBridgeServer
-> WebSocket connection to Cloudflare hostname
-> Cloudflare tunnel
-> private TCP origin inside dind-host-container
```

### Lifecycle

`UniversalBridgeServer` is designed to be used as a context manager:

- entering the context:
  - checks the requested local port is free
  - starts the local listener
  - starts the background accept loop
- inside the context:
  - each accepted client gets its own handler thread
  - each client handler starts two stream-forwarding threads:
    - local socket -> websocket
    - websocket -> local socket
- exiting the context:
  - sets the stop event
  - closes the listener
  - joins background threads

### Error Model

The bridge distinguishes between:

- bridge-wide failures
  - listener setup or accept-loop failures
  - exposed through `raise_if_failed()`
- per-client failures
  - client disconnects
  - websocket close events
  - idle websocket timeouts
  - logged, but not treated as fatal to the whole bridge

That distinction matters for long-lived host tools such as DBeaver. One idle
or closed client session should not kill the bridge server for every later
client.

### Idle Session Handling

`_websocket_to_socket()` treats idle read timeouts as non-fatal. On
`WebSocketTimeoutException`, it sends a ping and keeps the session alive if the
upstream path still responds.

That is why long-lived manual bridge runs now stay healthy even when a client
sits idle for a while before issuing the next query.

## Why This Is Separate

This code is kept separate from `src/experiment_runner.py` for a reason:

- `experiment_runner.py` owns proof orchestration, not byte transport
- `start_local_bridges.py` owns operator UX, not socket forwarding internals
- `bridge/universal.py` is the reusable transport primitive both callers share
- `bridge/local_bridges.py` and `bridge/start_local_bridges.py` are still
  bridge-owned because they define bridge-specific transport setup rather than
  general repository utilities

This keeps the transport layer generic and testable.

## Public API

### Constants

- `LOCALHOST`
  - fixed bind host: `127.0.0.1`
- `BUFFER_SIZE`
  - TCP/WebSocket chunk size

### Helper functions

- `wait_for_local_port(port, timeout_seconds)`
  - waits until the local listener accepts connections
- `ensure_port_available(port)`
  - fails early if a local port is already taken
- `build_access_headers()`
  - optionally attaches Cloudflare Access service-token headers if those env
    vars are present

### Main class

- `UniversalBridgeServer`
  - arguments:
    - `name`
    - `hostname`
    - `local_port`
    - `run_ts`
    - `raw_logs_dir`

Important methods:

- `__enter__()` / `__exit__()`
  - start and stop the bridge
- `raise_if_failed()`
  - surface bridge-wide failures to the caller
- `log()`
  - append a timestamped line to the raw bridge log

## How To Use

### Example: temporary PostgreSQL bridge

```python
from pathlib import Path

from bridge.universal import UniversalBridgeServer

with UniversalBridgeServer(
  name="postgres_client_bridge",
  hostname="60bf15690490.ratio1.link",
  local_port=15432,
  run_ts="demo_run",
  raw_logs_dir=Path("_logs/raw"),
) as bridge:
  bridge.raise_if_failed()
  input("bridge is running; press Enter to stop")
```

After that, any local PostgreSQL client can connect to:

- host: `127.0.0.1`
- port: `15432`

### Example: used by the automated experiment

`src/experiment_runner.py` starts two instances:

- PostgreSQL bridge
- Neo4j Bolt bridge

That allows the simulator modules to connect as if the services were local.

### Example: used by the manual host workflow

`src/bridge/start_local_bridges.py` uses the same class to expose stable local
ports for DBeaver and Bolt consumers.

## Logs

Each bridge writes one raw log file:

```text
_logs/raw/<RUN_TS>_<bridge-name>.log
```

Typical entries include:

- listener startup
- accepted clients
- non-fatal client stream endings
- bridge-wide fatal errors

## What This Component Does Not Do

`universal.py` itself does not:

- know PostgreSQL credentials
- know Neo4j credentials
- decide which services to expose
- provide the manual bridge CLI by itself
- perform service-specific verification queries

Those concerns belong to `src/bridge/start_local_bridges.py`,
`src/bridge/local_bridges.py`, `src/utils`, `src/simulators`, and
`src/experiment_runner.py`.
