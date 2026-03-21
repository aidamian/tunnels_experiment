"""Lazy imports for optional host-side runtime dependencies.

The host-side scripts support `--help` and other cheap control paths without
requiring all third-party database and WebSocket libraries to be installed
immediately. Modules should call the getters in this file at runtime instead of
importing those dependencies at module import time.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


INSTALL_HINT = (
  "missing host dependency. Run ./start_e2e.sh or install requirements-host.txt "
  "into the Python environment."
)


def _import_required_module(module_name: str) -> ModuleType:
  """Import a required runtime module or exit with a targeted message.

  Parameters
  ----------
  module_name:
    Module name to import dynamically.

  Returns
  -------
  ModuleType
    Imported Python module object.

  Raises
  ------
  SystemExit
    Raised when the requested dependency is not installed.

  Examples
  --------
  >>> module = _import_required_module("json")
  >>> module.__name__
  'json'
  """
  try:
    return import_module(module_name)
  except ModuleNotFoundError as exc:
    raise SystemExit(INSTALL_HINT) from exc


def get_psycopg_module() -> ModuleType:
  """Return the lazily imported `psycopg` module.

  Returns
  -------
  ModuleType
    Imported `psycopg` module.

  Examples
  --------
  The PostgreSQL simulator calls this immediately before opening a connection.
  """
  return _import_required_module("psycopg")


def get_requests_module() -> ModuleType:
  """Return the lazily imported `requests` module.

  Returns
  -------
  ModuleType
    Imported `requests` module.

  Examples
  --------
  The Neo4j HTTPS simulator calls this before issuing its HTTP POST request.
  """
  return _import_required_module("requests")


def get_websocket_module() -> ModuleType:
  """Return the lazily imported `websocket-client` module.

  Returns
  -------
  ModuleType
    Imported `websocket` module.

  Examples
  --------
  The universal bridge calls this before creating the Cloudflare websocket
  connection.
  """
  return _import_required_module("websocket")


def get_graph_database_class():
  """Return Neo4j's `GraphDatabase` class lazily.

  Returns
  -------
  type
    `neo4j.GraphDatabase` class.

  Examples
  --------
  The Neo4j Bolt simulator and manual bridge verification helper use this
  function before opening Bolt sessions.
  """
  return _import_required_module("neo4j").GraphDatabase
