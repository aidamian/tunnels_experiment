# Copyright (c) 2026 Ratio1

"""Shared local TCP bridge for Cloudflare-published TCP applications.

This module adapts Cloudflare-published TCP applications into ordinary local
TCP sockets. The consuming application talks to ``127.0.0.1:<port>`` using its
native protocol, while the bridge translates that byte stream into the
WebSocket transport Cloudflare Tunnel expects for published TCP services.

The implementation is deliberately world-neutral so both the real-machine
client flow and the app-side DinD flow can reuse the same transport code
without importing from one another.

Notes
-----
The bridge does not change application protocol semantics. PostgreSQL is still
PostgreSQL, Neo4j Bolt is still Bolt, and the bridge only handles byte
forwarding between a local TCP socket and ``wss://<published-hostname>``.

Examples
--------
Create a bridge object that can later be entered as a context manager:

>>> from pathlib import Path
>>> bridge = UniversalBridgeServer(
...   name="postgres_bridge",
...   hostname="example-tunnel.ratio1.link",
...   local_port=55432,
...   run_ts="260327_080712",
...   raw_logs_dir=Path("clients/_logs/raw"),
... )
>>> bridge.local_port
55432

Run the bridge while another client connects to the local port:

>>> from pathlib import Path
>>> with UniversalBridgeServer(
...   name="bolt_bridge",
...   hostname="example-tunnel.ratio1.link",
...   local_port=57687,
...   run_ts="260327_080712",
...   raw_logs_dir=Path("clients/_logs/raw"),
... ) as running_bridge:
...   running_bridge.raise_if_failed()

Run a single bridge directly as a foreground process:

``python3 shared/src/tunnel_common/universal.py --name postgres_bridge --hostname example-tunnel.ratio1.link --local-port 55432 --run-ts demo_run --raw-logs-dir clients/_logs/raw``
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any


RESET = "\033[0m"
COLORS = {
  "blue": "\033[34m",
  "cyan": "\033[36m",
  "green": "\033[32m",
  "red": "\033[31m",
  "yellow": "\033[33m",
}
LOCALHOST = "127.0.0.1"
BUFFER_SIZE = 64 * 1024
WEBSOCKET_INSTALL_HINT = (
  "missing websocket dependency. Install websocket-client in the active Python environment."
)


def colorize(message: str, color: str) -> str:
  """Wrap a message in an ANSI color code.

  Parameters
  ----------
  message:
    Plain log message to colorize.
  color:
    Symbolic color name from :data:`COLORS`.

  Returns
  -------
  str
    The formatted message. Unknown colors leave the message unmodified.

  Examples
  --------
  >>> colorize("bridge ready", "green").endswith(RESET)
  True
  >>> colorize("plain", "missing")
  'plain'
  """
  return f"{COLORS.get(color, '')}{message}{RESET if color in COLORS else ''}"


def format_line(scope: str, message: str) -> str:
  """Return a timestamped log line.

  Parameters
  ----------
  scope:
    Short subsystem name that will appear in square brackets.
  message:
    Human-readable log message.

  Returns
  -------
  str
    UTC timestamped line suitable for console and file logging.

  Examples
  --------
  >>> line = format_line("bridge", "listening")
  >>> "[bridge] listening" in line
  True
  """
  timestamp = datetime.now(timezone.utc).isoformat()
  return f"[{timestamp}] [{scope}] {message}"


def get_websocket_module() -> ModuleType:
  """Return the lazily imported ``websocket-client`` module.

  Returns
  -------
  ModuleType
    Imported ``websocket`` module from the ``websocket-client`` package.

  Raises
  ------
  SystemExit
    Raised with a focused installation hint when the dependency is missing.

  Notes
  -----
  Importing lazily keeps basic module import cheap and avoids failing in code
  paths that only need constants or helpers.

  Examples
  --------
  >>> module = get_websocket_module()
  >>> hasattr(module, "create_connection")
  True
  """
  try:
    return import_module("websocket")
  except ModuleNotFoundError as exc:
    raise SystemExit(WEBSOCKET_INSTALL_HINT) from exc


def wait_for_local_port(port: int, timeout_seconds: float) -> None:
  """Wait until a local TCP port starts accepting connections.

  Parameters
  ----------
  port:
    Local TCP port expected to accept connections.
  timeout_seconds:
    Maximum amount of time to wait before failing.

  Returns
  -------
  None
    This function returns only when the port is reachable.

  Raises
  ------
  RuntimeError
    Raised when the deadline expires before the port becomes reachable.

  Notes
  -----
  The bridge uses this immediately after starting its listener thread so the
  caller can safely treat the local endpoint as ready.

  Examples
  --------
  >>> import socket
  >>> listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  >>> listener.bind((LOCALHOST, 0))
  >>> listener.listen(1)
  >>> port = listener.getsockname()[1]
  >>> wait_for_local_port(port, timeout_seconds=1)
  >>> listener.close()
  """
  # Poll briefly instead of assuming the listener thread is ready immediately.
  deadline = time.time() + timeout_seconds
  while time.time() < deadline:
    try:
      with socket.create_connection((LOCALHOST, port), timeout=1):
        return
    except OSError:
      time.sleep(0.5)
  raise RuntimeError(f"local port {port} did not become reachable in time")


def build_access_headers() -> dict[str, str]:
  """Build optional Cloudflare Access headers for the WebSocket handshake.

  Returns
  -------
  dict[str, str]
    Header dictionary for ``websocket.create_connection``. The dictionary
    always includes a ``User-Agent`` and conditionally includes Cloudflare
    Access service-token headers when both related environment variables exist.

  Notes
  -----
  Supported environment variables are:

  - ``CF_ACCESS_SERVICE_TOKEN_ID``
  - ``CF_ACCESS_SERVICE_TOKEN_SECRET``

  Examples
  --------
  >>> headers = build_access_headers()
  >>> headers["User-Agent"]
  'tunnels-experiment-bridge/2.0'
  """
  headers = {"User-Agent": "tunnels-experiment-bridge/2.0"}
  # Only send Access headers when a complete service-token pair is available.
  service_token_id = os.environ.get("CF_ACCESS_SERVICE_TOKEN_ID", "")
  service_token_secret = os.environ.get("CF_ACCESS_SERVICE_TOKEN_SECRET", "")
  if service_token_id and service_token_secret:
    headers["Cf-Access-Client-Id"] = service_token_id
    headers["Cf-Access-Client-Secret"] = service_token_secret
  return headers


def close_socket_quietly(sock: socket.socket | None) -> None:
  """Close a socket while suppressing cleanup errors.

  Parameters
  ----------
  sock:
    Socket to close. ``None`` is accepted for convenience.

  Returns
  -------
  None
    Cleanup helper with no return value.

  Notes
  -----
  Shutdown and close operations can legitimately fail during teardown if the
  peer has already gone away, so cleanup noise is intentionally suppressed.

  Examples
  --------
  >>> sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  >>> close_socket_quietly(sock)
  """
  if sock is None:
    return
  try:
    sock.shutdown(socket.SHUT_RDWR)
  except OSError:
    pass
  try:
    sock.close()
  except OSError:
    pass


def close_websocket_quietly(ws: Any) -> None:
  """Close a WebSocket connection while suppressing cleanup errors.

  Parameters
  ----------
  ws:
    WebSocket-like object exposing a ``close`` method. ``None`` is accepted.

  Returns
  -------
  None
    Cleanup helper with no return value.

  Examples
  --------
  >>> class DummySocket:
  ...   def __init__(self):
  ...     self.closed = False
  ...   def close(self):
  ...     self.closed = True
  >>> dummy = DummySocket()
  >>> close_websocket_quietly(dummy)
  >>> dummy.closed
  True
  """
  if ws is None:
    return
  try:
    ws.close()
  except Exception:
    pass


def ensure_port_available(port: int) -> None:
  """Fail early if the selected local bridge port is already in use.

  Parameters
  ----------
  port:
    Local TCP port that the bridge intends to bind.

  Returns
  -------
  None
    This helper succeeds silently when the port is available.

  Raises
  ------
  RuntimeError
    Raised when the port is already bound by another process.

  Examples
  --------
  >>> ensure_port_available(6553)
  """
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
      # Bind a short-lived probe socket so failures happen before the real
      # listener thread is started.
      probe.bind((LOCALHOST, port))
    except OSError as exc:
      raise RuntimeError(f"local port {port} is already in use") from exc


@dataclass
class UniversalBridgeServer:
  """Expose a local TCP listener backed by a Cloudflare TCP application.

  Parameters
  ----------
  name:
    Human-readable bridge name used in logs and thread names.
  hostname:
    Public Cloudflare Tunnel hostname for the published TCP application.
  local_port:
    Localhost TCP port on which the bridge should listen.
  run_ts:
    Run identifier used to make raw log file names unique and traceable.
  raw_logs_dir:
    Directory where bridge log files should be written.
  log_color:
    ANSI color name for this bridge instance's log lines.

  Attributes
  ----------
  listener:
    Listening socket bound to ``127.0.0.1`` once the context is entered.
  server_thread:
    Background thread accepting local client connections.
  stop_event:
    Process-wide stop signal shared by the accept loop and per-client pumps.
  error:
    First terminal error observed by the bridge, if any.
  log_path:
    Concrete path of the raw log file for this bridge instance.

  Notes
  -----
  The bridge is designed to be used as a context manager. Entering the context
  starts the local listener and leaving the context tears down the listener,
  connection handlers, and active WebSocket sessions.

  Examples
  --------
  >>> from pathlib import Path
  >>> with UniversalBridgeServer(
  ...   name="postgres_bridge",
  ...   hostname="example-tunnel.ratio1.link",
  ...   local_port=55432,
  ...   run_ts="260327_080712",
  ...   raw_logs_dir=Path("clients/_logs/raw"),
  ... ) as bridge:
  ...   bridge.raise_if_failed()
  """

  name: str
  hostname: str
  local_port: int
  run_ts: str
  raw_logs_dir: Path
  log_color: str = "cyan"

  def __post_init__(self) -> None:
    """Initialize runtime-only attributes after dataclass field assignment.

    Returns
    -------
    None
      The dataclass hook mutates the instance in place.

    Notes
    -----
    These attributes are kept out of the constructor because they are internal
    runtime state, not part of the external bridge contract.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> bridge.listener is None
    True
    """
    self.listener: socket.socket | None = None
    self.server_thread: threading.Thread | None = None
    self.stop_event = threading.Event()
    self.error: Exception | None = None
    self.error_lock = threading.Lock()
    self.log_path = self.raw_logs_dir / f"{self.run_ts}_{self.name}.log"
    # Handler threads are tracked so shutdown waits for in-flight sessions.
    self.handler_threads: list[threading.Thread] = []

  def log(self, message: str) -> None:
    """Append one bridge log line to the raw log file.

    Parameters
    ----------
    message:
      Human-readable message body without timestamp or scope prefix.

    Returns
    -------
    None
      This helper writes directly to disk.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> bridge.log("example message")
    """
    # Ensure the directory exists even when the first log entry is an error.
    self.raw_logs_dir.mkdir(parents=True, exist_ok=True)
    line = format_line(self.name, message)
    with self.log_path.open("a", encoding="utf-8") as handle:
      handle.write(colorize(line, self.log_color) + "\n")

  def __enter__(self) -> "UniversalBridgeServer":
    """Start the local listener and return the running bridge.

    Returns
    -------
    UniversalBridgeServer
      The running bridge instance for use inside a ``with`` block.

    Raises
    ------
    RuntimeError
      Raised if the requested local port is already in use or the listener does
      not become reachable in time.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> entered = bridge.__enter__()
    >>> entered is bridge
    True
    >>> bridge.__exit__(None, None, None)
    """
    ensure_port_available(self.local_port)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((LOCALHOST, self.local_port))
    listener.listen(5)
    # A short timeout keeps accept() interruptible so shutdown is responsive.
    listener.settimeout(1)
    self.listener = listener
    self.server_thread = threading.Thread(target=self._serve, name=f"bridge-{self.name}", daemon=True)
    self.server_thread.start()
    self.log(f"listening on {LOCALHOST}:{self.local_port} for hostname {self.hostname}")
    # Probe the port before returning so callers can launch clients immediately.
    wait_for_local_port(self.local_port, timeout_seconds=5)
    return self

  def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
    """Stop the bridge and wait briefly for background threads to exit.

    Parameters
    ----------
    exc_type:
      Exception type supplied by the context manager protocol.
    exc:
      Exception instance supplied by the context manager protocol.
    tb:
      Traceback object supplied by the context manager protocol.

    Returns
    -------
    None
      The context manager performs best-effort cleanup in place.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> _ = bridge.__enter__()
    >>> bridge.__exit__(None, None, None)
    """
    # Tell both the accept loop and all connection handlers to stop.
    self.stop_event.set()
    close_socket_quietly(self.listener)
    if self.server_thread is not None:
      self.server_thread.join(timeout=5)
    for thread in self.handler_threads:
      thread.join(timeout=5)

  def raise_if_failed(self) -> None:
    """Raise a runtime error if the bridge previously recorded a failure.

    Returns
    -------
    None
      Returns silently when the bridge is healthy.

    Raises
    ------
    RuntimeError
      Raised when a background bridge component already failed.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> bridge.raise_if_failed()
    """
    if self.error is not None:
      raise RuntimeError(f"{self.name} failed: {self.error}") from self.error

  def _set_error(self, exc: Exception) -> None:
    """Record the first terminal bridge error and log it.

    Parameters
    ----------
    exc:
      Exception to store as the bridge's failure reason.

    Returns
    -------
    None
      Mutates the bridge instance in place.

    Notes
    -----
    Only the first failure is preserved so later cascade errors do not hide the
    original cause.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> bridge._set_error(RuntimeError("boom"))
    >>> isinstance(bridge.error, RuntimeError)
    True
    """
    with self.error_lock:
      # Preserve the first meaningful failure and ignore follow-on cleanup noise.
      if self.error is None:
        self.error = exc
        self.log(f"bridge error: {exc}")

  def _serve(self) -> None:
    """Accept local TCP clients and dispatch a handler thread per connection.

    Returns
    -------
    None
      The accept loop runs until the bridge is stopped or a fatal error occurs.

    Notes
    -----
    Each local client gets its own handler thread pair so concurrent consumers
    do not block one another.

    Examples
    --------
    This method is started internally by :meth:`__enter__` and is not normally
    called directly.
    """
    assert self.listener is not None
    try:
      while not self.stop_event.is_set():
        try:
          client_socket, address = self.listener.accept()
        except socket.timeout:
          # Wake up periodically so the loop notices stop_event promptly.
          continue
        except OSError:
          if self.stop_event.is_set():
            return
          raise

        # Each client session owns its own WebSocket and byte-pump threads.
        handler = threading.Thread(
          target=self._handle_client,
          args=(client_socket, address),
          name=f"bridge-client-{self.name}",
          daemon=True,
        )
        self.handler_threads.append(handler)
        handler.start()
    except Exception as exc:
      if not self.stop_event.is_set():
        self._set_error(exc)

  def _log_client_issue(self, address: tuple[str, int], message: str) -> None:
    """Log a client-scoped issue with the peer address attached.

    Parameters
    ----------
    address:
      Local client peer address as returned by ``socket.accept``.
    message:
      Human-readable failure or disconnect detail.

    Returns
    -------
    None
      Convenience wrapper around :meth:`log`.

    Examples
    --------
    >>> from pathlib import Path
    >>> bridge = UniversalBridgeServer(
    ...   name="demo",
    ...   hostname="example-tunnel.ratio1.link",
    ...   local_port=55432,
    ...   run_ts="run",
    ...   raw_logs_dir=Path("logs"),
    ... )
    >>> bridge._log_client_issue(("127.0.0.1", 12345), "closed")
    """
    self.log(f"client {address[0]}:{address[1]} issue: {message}")

  def _handle_client(self, client_socket: socket.socket, address: tuple[str, int]) -> None:
    """Bridge one accepted local client to one Cloudflare WebSocket session.

    Parameters
    ----------
    client_socket:
      Accepted local TCP client socket.
    address:
      Local peer address tuple for logging.

    Returns
    -------
    None
      Runs until either side disconnects or a failure occurs.

    Notes
    -----
    This method creates two worker threads for the session:

    - local TCP socket -> WebSocket
    - WebSocket -> local TCP socket

    Examples
    --------
    This method is called internally by :meth:`_serve` for each accepted
    connection.
    """
    websocket = get_websocket_module()
    ws: Any = None
    # This event coordinates shutdown between the two per-direction stream pumps.
    local_stop = threading.Event()
    try:
      self.log(f"accepted client {address[0]}:{address[1]}")
      client_socket.settimeout(1)
      headers = [f"{key}: {value}" for key, value in build_access_headers().items()]

      # The public TCP application is consumed through a WebSocket session.
      ws = websocket.create_connection(
        f"wss://{self.hostname}",
        header=headers,
        timeout=20,
        enable_multithread=True,
      )

      # Run the two directions independently so either side can backpressure
      # without stalling the opposite direction's reads.
      upstream = threading.Thread(
        target=self._socket_to_websocket,
        args=(client_socket, ws, local_stop),
        name=f"sock-to-ws-{self.name}",
        daemon=True,
      )
      downstream = threading.Thread(
        target=self._websocket_to_socket,
        args=(client_socket, ws, local_stop),
        name=f"ws-to-sock-{self.name}",
        daemon=True,
      )
      upstream.start()
      downstream.start()
      upstream.join()
      downstream.join()
    except Exception as exc:
      if not self.stop_event.is_set() and not local_stop.is_set():
        self._log_client_issue(address, str(exc))
    finally:
      # Always signal both stream pumps to exit before tearing down transports.
      local_stop.set()
      close_websocket_quietly(ws)
      close_socket_quietly(client_socket)

  def _socket_to_websocket(
    self,
    client_socket: socket.socket,
    ws: Any,
    stop_event: threading.Event,
  ) -> None:
    """Pump bytes from the local TCP socket into the WebSocket stream.

    Parameters
    ----------
    client_socket:
      Accepted local TCP client socket.
    ws:
      Active WebSocket connection to the published TCP application.
    stop_event:
      Per-session event used to coordinate shutdown with the opposite stream
      pump.

    Returns
    -------
    None
      The loop exits when either side closes or a failure occurs.

    Examples
    --------
    This method is spawned internally by :meth:`_handle_client`.
    """
    websocket = get_websocket_module()
    try:
      while not stop_event.is_set() and not self.stop_event.is_set():
        try:
          data = client_socket.recv(BUFFER_SIZE)
        except socket.timeout:
          # Timeouts are expected; they let the loop re-check stop conditions.
          continue
        if not data:
          # EOF from the local client means the session should shut down cleanly.
          return
        ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
    except Exception as exc:
      if not self.stop_event.is_set() and not stop_event.is_set():
        self.log(f"socket-to-websocket client stream ended: {exc}")
    finally:
      stop_event.set()

  def _websocket_to_socket(
    self,
    client_socket: socket.socket,
    ws: Any,
    stop_event: threading.Event,
  ) -> None:
    """Pump bytes from the WebSocket stream back into the local TCP socket.

    Parameters
    ----------
    client_socket:
      Accepted local TCP client socket.
    ws:
      Active WebSocket connection to the published TCP application.
    stop_event:
      Per-session event used to coordinate shutdown with the opposite stream
      pump.

    Returns
    -------
    None
      The loop exits when either side closes or a failure occurs.

    Notes
    -----
    ``websocket-client`` surfaces idle reads as timeout exceptions. The bridge
    treats those timeouts as keepalive opportunities and sends ``ping`` frames
    instead of treating them as failures.

    Examples
    --------
    This method is spawned internally by :meth:`_handle_client`.
    """
    websocket = get_websocket_module()
    try:
      while not stop_event.is_set() and not self.stop_event.is_set():
        try:
          message = ws.recv()
        except websocket.WebSocketTimeoutException:
          try:
            # Keep the session warm across idle periods instead of disconnecting.
            ws.ping()
          except Exception:
            return
          continue
        if message is None:
          return
        # websocket-client may deliver text or bytes; the TCP socket always
        # expects a byte payload.
        payload = message.encode("utf-8") if isinstance(message, str) else message
        if payload:
          client_socket.sendall(payload)
    except websocket.WebSocketConnectionClosedException:
      return
    except Exception as exc:
      if not self.stop_event.is_set() and not stop_event.is_set():
        self.log(f"websocket-to-socket client stream ended: {exc}")
    finally:
      stop_event.set()


def parse_args() -> argparse.Namespace:
  """Parse CLI arguments for running a single bridge process.

  Returns
  -------
  argparse.Namespace
    Parsed arguments describing the public tunnel hostname, local listener,
    and logging configuration for one bridge instance.

  Examples
  --------
  Run a long-lived PostgreSQL bridge:

  ``python3 shared/src/tunnel_common/universal.py --name postgres_bridge --hostname example-tunnel.ratio1.link --local-port 55432 --run-ts demo_run --raw-logs-dir clients/_logs/raw``

  Run a short-lived bridge for a smoke test:

  ``python3 shared/src/tunnel_common/universal.py --name bolt_bridge --hostname example-tunnel.ratio1.link --local-port 57687 --run-ts demo_run --raw-logs-dir clients/_logs/raw --duration-seconds 5``
  """
  parser = argparse.ArgumentParser(
    description=(
      "Expose one localhost TCP listener that relays to one Cloudflare-published "
      "TCP application over WebSocket."
    )
  )
  parser.add_argument("--name", required=True, help="human-readable bridge name for logs and thread labels")
  parser.add_argument("--hostname", required=True, help="public Cloudflare Tunnel hostname for the TCP application")
  parser.add_argument("--local-port", required=True, type=int, help="localhost TCP port to bind")
  parser.add_argument("--run-ts", required=True, help="run identifier used in raw log file names")
  parser.add_argument("--raw-logs-dir", required=True, type=Path, help="directory where bridge log files will be written")
  parser.add_argument("--log-color", default="cyan", help="ANSI log color name to use for file log lines")
  parser.add_argument(
    "--duration-seconds",
    type=int,
    help="optional finite runtime for the bridge process; default is to run until interrupted",
  )
  return parser.parse_args()


def main() -> int:
  """Run one bridge as a foreground process.

  Returns
  -------
  int
    Zero when the bridge exits cleanly, either after the requested duration or
    after an interrupt signal.

  Raises
  ------
  RuntimeError
    Raised when the bridge records a background failure.

  Examples
  --------
  >>> # python3 shared/src/tunnel_common/universal.py --name postgres_bridge --hostname example-tunnel.ratio1.link --local-port 55432 --run-ts demo_run --raw-logs-dir clients/_logs/raw
  """
  args = parse_args()
  bridge = UniversalBridgeServer(
    name=args.name,
    hostname=args.hostname,
    local_port=args.local_port,
    run_ts=args.run_ts,
    raw_logs_dir=args.raw_logs_dir,
    log_color=args.log_color,
  )

  try:
    with bridge:
      if args.duration_seconds is not None:
        deadline = time.monotonic() + args.duration_seconds
        while time.monotonic() < deadline:
          bridge.raise_if_failed()
          time.sleep(0.5)
        bridge.raise_if_failed()
        return 0

      while True:
        # Stay in the foreground as a simple daemon process and surface any
        # asynchronous bridge failures promptly.
        bridge.raise_if_failed()
        time.sleep(1)
  except KeyboardInterrupt:
    bridge.log("received interrupt, stopping bridge")
    return 0


if __name__ == "__main__":
  raise SystemExit(main())
