"""Local TCP bridge for Cloudflare-published TCP applications."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.console import colorize, format_line
from utils.dependencies import get_websocket_module


LOCALHOST = "127.0.0.1"
BUFFER_SIZE = 64 * 1024


def wait_for_local_port(port: int, timeout_seconds: float) -> None:
  deadline = time.time() + timeout_seconds
  while time.time() < deadline:
    try:
      with socket.create_connection((LOCALHOST, port), timeout=1):
        return
    except OSError:
      time.sleep(0.5)
  raise RuntimeError(f"local port {port} did not become reachable in time")


def close_socket_quietly(sock: socket.socket | None) -> None:
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
  if ws is None:
    return
  try:
    ws.close()
  except Exception:
    pass


def ensure_port_available(port: int) -> None:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
      probe.bind((LOCALHOST, port))
    except OSError as exc:
      raise RuntimeError(f"local port {port} is already in use") from exc


@dataclass
class UniversalBridgeServer:
  name: str
  hostname: str
  local_port: int
  run_ts: str
  raw_logs_dir: Path
  log_color: str = "green"

  def __post_init__(self) -> None:
    self.listener: socket.socket | None = None
    self.server_thread: threading.Thread | None = None
    self.stop_event = threading.Event()
    self.error: Exception | None = None
    self.error_lock = threading.Lock()
    self.log_path = self.raw_logs_dir / f"{self.run_ts}_{self.name}.log"
    self.handler_threads: list[threading.Thread] = []

  def log(self, message: str) -> None:
    self.raw_logs_dir.mkdir(parents=True, exist_ok=True)
    line = format_line(self.name, message)
    with self.log_path.open("a", encoding="utf-8") as handle:
      handle.write(colorize(line, self.log_color) + "\n")

  def __enter__(self) -> UniversalBridgeServer:
    ensure_port_available(self.local_port)
    self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.listener.bind((LOCALHOST, self.local_port))
    self.listener.listen(8)
    self.listener.settimeout(1.0)
    self.server_thread = threading.Thread(target=self._serve_forever, daemon=True)
    self.server_thread.start()
    wait_for_local_port(self.local_port, timeout_seconds=5)
    self.log(f"listening on {LOCALHOST}:{self.local_port} for wss://{self.hostname}")
    return self

  def __exit__(self, exc_type: Any, exc: Any, exc_tb: Any) -> None:
    self.stop_event.set()
    close_socket_quietly(self.listener)
    if self.server_thread is not None:
      self.server_thread.join(timeout=2)
    for thread in self.handler_threads:
      thread.join(timeout=2)

  def raise_if_failed(self) -> None:
    with self.error_lock:
      if self.error is not None:
        raise RuntimeError(str(self.error)) from self.error

  def _record_error(self, exc: Exception) -> None:
    with self.error_lock:
      if self.error is None:
        self.error = exc
    self.log(f"bridge failed: {exc}")
    self.stop_event.set()
    close_socket_quietly(self.listener)

  def _serve_forever(self) -> None:
    try:
      while not self.stop_event.is_set():
        try:
          client_socket, client_address = self.listener.accept()
        except socket.timeout:
          continue
        except OSError:
          if self.stop_event.is_set():
            return
          raise

        handler_thread = threading.Thread(
          target=self._handle_client,
          args=(client_socket, client_address),
          daemon=True,
        )
        handler_thread.start()
        self.handler_threads.append(handler_thread)
    except Exception as exc:
      self._record_error(exc)

  def _handle_client(self, client_socket: socket.socket, client_address: tuple[str, int]) -> None:
    websocket = None
    self.log(f"accepted local TCP client from {client_address[0]}:{client_address[1]}")
    try:
      websocket_module = get_websocket_module()
      websocket = websocket_module.create_connection(
        f"wss://{self.hostname}",
        timeout=15,
        enable_multithread=True,
        header=["User-Agent: tunnels-experiment-app-bridge/1.0"],
      )

      upstream_thread = threading.Thread(
        target=self._pump_client_to_websocket,
        args=(client_socket, websocket),
        daemon=True,
      )
      downstream_thread = threading.Thread(
        target=self._pump_websocket_to_client,
        args=(websocket, client_socket),
        daemon=True,
      )
      upstream_thread.start()
      downstream_thread.start()
      upstream_thread.join()
      downstream_thread.join()
    except Exception as exc:
      self.log(f"connection relay failed for {client_address[0]}:{client_address[1]}: {exc}")
    finally:
      close_websocket_quietly(websocket)
      close_socket_quietly(client_socket)

  def _pump_client_to_websocket(self, client_socket: socket.socket, websocket: Any) -> None:
    try:
      while not self.stop_event.is_set():
        payload = client_socket.recv(BUFFER_SIZE)
        if not payload:
          try:
            websocket.send("", opcode=0x8)
          except Exception:
            pass
          return
        websocket.send(payload, opcode=0x2)
    except Exception:
      return

  def _pump_websocket_to_client(self, websocket: Any, client_socket: socket.socket) -> None:
    try:
      while not self.stop_event.is_set():
        frame = websocket.recv()
        if frame is None:
          return
        if isinstance(frame, str):
          frame = frame.encode("utf-8")
        client_socket.sendall(frame)
    except Exception:
      return
