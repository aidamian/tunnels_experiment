"""Local TCP bridge for Cloudflare-published TCP applications.

Cloudflare's published TCP applications are carried over a WebSocket transport
on the client side. This module hides that transport detail behind an ordinary
localhost TCP listener so tools such as PostgreSQL clients or Neo4j Bolt
drivers can connect as if the service were local.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.dependencies import get_websocket_module


LOCALHOST = "127.0.0.1"
BUFFER_SIZE = 64 * 1024


def wait_for_local_port(port: int, timeout_seconds: float) -> None:
  """Wait until a local TCP port starts accepting connections.

  This helper is used immediately after listener startup so callers can safely
  treat the bridge port as ready before they launch a client against it.

  Parameters
  ----------
  port:
    Local TCP port to probe.
  timeout_seconds:
    Maximum number of seconds to wait.

  Raises
  ------
  RuntimeError
    Raised when the port does not become reachable before the timeout.

  Examples
  --------
  After creating a listener on ``127.0.0.1:15432``:

  >>> wait_for_local_port(15432, timeout_seconds=5)
  """
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

  The manual and automated bridge flows do not require these headers in the
  default repository topology, but the transport can attach them if the public
  hostname is additionally protected by Cloudflare Access service tokens.

  Returns
  -------
  dict[str, str]
    Header dictionary for `websocket.create_connection`.

  Examples
  --------
  >>> headers = build_access_headers()
  >>> "User-Agent" in headers
  True
  """
  # These headers are optional and only matter if the tunnel hostname is also
  # protected by Cloudflare Access service tokens.
  headers = {"User-Agent": "tunnels-experiment-host-client/2.0"}
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
    Socket to close, or `None`.

  Returns
  -------
  None
    This helper only performs cleanup and returns ``None``.

  Examples
  --------
  The bridge calls this during shutdown and per-client cleanup after either
  side closes the stream.
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
    WebSocket connection object, or `None`.

  Returns
  -------
  None
    This helper only performs cleanup and returns ``None``.

  Examples
  --------
  The bridge uses this when a client stream ends or the bridge context exits.
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
    Local TCP port to reserve.

  Raises
  ------
  RuntimeError
    Raised when another local process already owns the port.

  Examples
  --------
  >>> ensure_port_available(55432)
  """
  # Probe-bind first so the operator gets a clear failure before the bridge
  # starts its background threads.
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
      probe.bind((LOCALHOST, port))
    except OSError as exc:
      raise RuntimeError(f"local port {port} is already in use") from exc


@dataclass
class UniversalBridgeServer:
  """Expose a local TCP listener backed by a Cloudflare TCP application.

  The server accepts ordinary localhost TCP clients and forwards their byte
  streams to a Cloudflare-published TCP application over WebSocket. From the
  point of view of local tools such as DBeaver, ``psycopg``, or Neo4j Bolt
  drivers, the service looks like a normal local TCP socket.

  Attributes
  ----------
  name:
    Human-readable bridge name used in log file names.
  hostname:
    Public Cloudflare hostname serving the TCP application.
  local_port:
    Localhost TCP port exposed by the bridge.
  run_ts:
    Current run identifier used in log file names.
  raw_logs_dir:
    Directory where bridge logs are written.

  Examples
  --------
  >>> from pathlib import Path
  >>> with UniversalBridgeServer(
  ...   name="postgres_client_bridge",
  ...   hostname="60bf15690490.ratio1.link",
  ...   local_port=15432,
  ...   run_ts="demo_run",
  ...   raw_logs_dir=Path("_logs/raw"),
  ... ) as server:
  ...   server.raise_if_failed()
  """

  name: str
  hostname: str
  local_port: int
  run_ts: str
  raw_logs_dir: Path

  def __post_init__(self) -> None:
    """Initialize mutable runtime state for the bridge.

    Returns
    -------
    None
      The dataclass stores initialized mutable fields on ``self``.

    Examples
    --------
    This method runs automatically after dataclass construction and does not
    need to be called directly by bridge consumers.
    """
    self.listener: socket.socket | None = None
    self.server_thread: threading.Thread | None = None
    self.stop_event = threading.Event()
    self.error: Exception | None = None
    self.error_lock = threading.Lock()
    self.log_path = self.raw_logs_dir / f"{self.run_ts}_{self.name}.log"
    self.handler_threads: list[threading.Thread] = []

  def log(self, message: str) -> None:
    """Append a timestamped bridge log message.

    Parameters
    ----------
    message:
      Log message to append.

    Returns
    -------
    None
      The message is appended to the bridge's raw log file.

    Examples
    --------
    >>> server = UniversalBridgeServer("demo", "example.com", 12345, "run", Path("_logs/raw"))
    >>> server.log("bridge started")
    """
    self.raw_logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with self.log_path.open("a", encoding="utf-8") as handle:
      handle.write(f"[{timestamp}] {message}\n")

  def __enter__(self) -> "UniversalBridgeServer":
    """Start the local TCP listener and background accept loop.

    The returned bridge instance is ready to accept localhost TCP clients and
    relay them to the configured ``wss://`` hostname.

    Returns
    -------
    UniversalBridgeServer
      Running bridge instance.

    Examples
    --------
    >>> with UniversalBridgeServer(
    ...   name="neo4j_bolt_client_bridge",
    ...   hostname="99c7e7089d1b.ratio1.link",
    ...   local_port=17687,
    ...   run_ts="demo_run",
    ...   raw_logs_dir=Path("_logs/raw"),
    ... ) as bridge:
    ...   bridge.raise_if_failed()
    """
    # Create the local listener before any connection attempts begin so callers
    # can reliably point clients at the published local port.
    ensure_port_available(self.local_port)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((LOCALHOST, self.local_port))
    listener.listen(5)
    listener.settimeout(1)
    self.listener = listener
    self.server_thread = threading.Thread(target=self._serve, name=f"bridge-{self.name}", daemon=True)
    self.server_thread.start()
    self.log(f"listening on {LOCALHOST}:{self.local_port} for hostname {self.hostname}")
    wait_for_local_port(self.local_port, timeout_seconds=5)
    return self

  def __exit__(self, exc_type, exc, tb) -> None:
    """Stop the listener and join worker threads.

    Parameters
    ----------
    exc_type:
      Exception type received from the context manager, if any.
    exc:
      Exception instance received from the context manager, if any.
    tb:
      Traceback received from the context manager, if any.

    Returns
    -------
    None
      The listener and background threads are shut down in place.

    Examples
    --------
    This method runs automatically when leaving the ``with`` block that owns
    the bridge.
    """
    self.stop_event.set()
    close_socket_quietly(self.listener)
    if self.server_thread is not None:
      self.server_thread.join(timeout=5)
    for thread in self.handler_threads:
      thread.join(timeout=5)

  def raise_if_failed(self) -> None:
    """Raise the first worker failure observed by the bridge.

    Callers poll this method while the bridge stays up in the foreground. It
    only reports bridge-wide failures, not routine per-client disconnects.

    Raises
    ------
    RuntimeError
      Raised when a worker thread recorded a bridge error.

    Examples
    --------
    >>> bridge.raise_if_failed()
    """
    if self.error is not None:
      raise RuntimeError(f"{self.name} failed: {self.error}") from self.error

  def _set_error(self, exc: Exception) -> None:
    """Record the first worker error and mirror it to the bridge log.

    Parameters
    ----------
    exc:
      Exception to record.

    Returns
    -------
    None
      The first observed bridge-wide error is stored on ``self.error``.

    Examples
    --------
    Fatal accept-loop failures record their first exception here so the
    foreground owner can surface it through :meth:`raise_if_failed`.
    """
    with self.error_lock:
      if self.error is None:
        self.error = exc
        self.log(f"bridge error: {exc}")

  def _serve(self) -> None:
    """Accept local TCP clients and start a worker thread for each one.

    Returns
    -------
    None
      The accept loop runs until the bridge is stopped or a fatal listener
      error occurs.

    Examples
    --------
    This listener loop is started on a background thread from
    :meth:`__enter__` and stays alive for the lifetime of the bridge context.
    """
    assert self.listener is not None
    try:
      while not self.stop_event.is_set():
        try:
          client_socket, address = self.listener.accept()
        except socket.timeout:
          continue
        except OSError:
          if self.stop_event.is_set():
            return
          raise

        # One worker thread per local client keeps the bridge simple and mirrors
        # how a local TCP proxy is typically structured.
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
    """Record a non-fatal per-client bridge issue.

    Parameters
    ----------
    address:
      Client address tuple returned by `accept()`.
    message:
      Human-readable issue description.

    Returns
    -------
    None
      The issue is logged without marking the whole bridge as failed.

    Examples
    --------
    One disconnected DBeaver session is reported here without shutting down
    later sessions on the same bridge listener.
    """
    self.log(f"client {address[0]}:{address[1]} issue: {message}")

  def _handle_client(self, client_socket: socket.socket, address: tuple[str, int]) -> None:
    """Bridge one local TCP client to one Cloudflare WebSocket session.

    Parameters
    ----------
    client_socket:
      Accepted local TCP client socket.
    address:
      Client address tuple returned by `accept()`.

    Returns
    -------
    None
      The method owns one complete client session and returns when that
      session ends.

    Examples
    --------
    Each accepted PostgreSQL or Bolt client gets one call to this method and
    one dedicated Cloudflare WebSocket session.
    """
    websocket = get_websocket_module()
    ws: Any = None
    local_stop = threading.Event()
    try:
      self.log(f"accepted client {address[0]}:{address[1]}")
      client_socket.settimeout(1)
      headers = [f"{key}: {value}" for key, value in build_access_headers().items()]

      # Cloudflare's published TCP applications are exposed to clients over
      # WebSocket, so the bridge creates that WebSocket session on behalf of the
      # local TCP client.
      ws = websocket.create_connection(
        f"wss://{self.hostname}",
        header=headers,
        timeout=20,
        enable_multithread=True,
      )

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

      # Keep both directions alive until either side closes or fails.
      upstream.join()
      downstream.join()
    except Exception as exc:
      if not self.stop_event.is_set() and not local_stop.is_set():
        self._log_client_issue(address, str(exc))
    finally:
      local_stop.set()
      close_websocket_quietly(ws)
      close_socket_quietly(client_socket)

  def _socket_to_websocket(
    self,
    client_socket: socket.socket,
    ws: Any,
    stop_event: threading.Event,
  ) -> None:
    """Forward bytes from the local TCP socket to Cloudflare.

    Parameters
    ----------
    client_socket:
      Local TCP client socket.
    ws:
      Connected Cloudflare WebSocket session.
    stop_event:
      Shared per-client stop signal.

    Returns
    -------
    None
      The method exits when the client closes, the bridge stops, or the
      per-client stop signal is set.

    Examples
    --------
    PostgreSQL startup packets and Bolt handshake bytes flow through this
    method from the local TCP client socket to the Cloudflare WebSocket.
    """
    websocket = get_websocket_module()
    try:
      while not stop_event.is_set() and not self.stop_event.is_set():
        try:
          data = client_socket.recv(BUFFER_SIZE)
        except socket.timeout:
          continue
        if not data:
          return

        # Database-driver bytes from the local TCP socket become binary
        # WebSocket frames carried through Cloudflare.
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
    """Forward Cloudflare payloads back to the local TCP client.

    Parameters
    ----------
    client_socket:
      Local TCP client socket.
    ws:
      Connected Cloudflare WebSocket session.
    stop_event:
      Shared per-client stop signal.

    Returns
    -------
    None
      The method exits when the websocket closes, the bridge stops, or the
      per-client stop signal is set.

    Examples
    --------
    Database responses carried as WebSocket frames are written back to the
    local TCP client through this method.

    Notes
    -----
    Idle ``ws.recv()`` timeouts are treated as keepalive events. The bridge
    sends a ping and keeps the session alive if the upstream path still
    responds.
    """
    websocket = get_websocket_module()
    try:
      while not stop_event.is_set() and not self.stop_event.is_set():
        try:
          message = ws.recv()
        except websocket.WebSocketTimeoutException:
          # An idle bridge session is still healthy. Optionally send a ping so
          # long-lived host tools such as DBeaver can keep the session warm.
          try:
            ws.ping()
          except Exception:
            return
          continue
        if message is None:
          return
        payload = message.encode("utf-8") if isinstance(message, str) else message
        if payload:
          # Frames coming back from Cloudflare are restored to raw TCP bytes on
          # the local client socket.
          client_socket.sendall(payload)
    except websocket.WebSocketConnectionClosedException:
      return
    except Exception as exc:
      if not self.stop_event.is_set() and not stop_event.is_set():
        self.log(f"websocket-to-socket client stream ended: {exc}")
    finally:
      stop_event.set()
