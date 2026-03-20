"""Helpers for manual localhost bridges backed by tunnel FQDNs.

This module is intentionally client-side-cloudflared-free. It builds ordinary
localhost TCP listeners that relay bytes directly to the public tunnel FQDNs
over WebSocket using the repository's own Python bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.dependencies import get_graph_database_class, get_psycopg_module
from utils.envfiles import load_env_file


LOCALHOST = "127.0.0.1"


@dataclass(frozen=True)
class BridgeSpec:
  """Describe one manual localhost bridge."""

  service_key: str
  public_host_env_key: str
  local_port: int
  purpose: str


def repo_root() -> Path:
  """Return the repository root."""
  return Path(__file__).resolve().parents[2]


def runtime_env_path() -> Path:
  """Return the generated runtime env-file path."""
  return repo_root() / ".runtime" / "tunnels.env"


def load_runtime_env() -> dict[str, str]:
  """Load the generated runtime environment."""
  path = runtime_env_path()
  if not path.exists():
    raise FileNotFoundError(
      f"{path} does not exist. Run `python3 src/utils/prepare_runtime.py` first."
    )
  return load_env_file(path)


def default_specs(postgres_port: int, neo4j_port: int) -> list[BridgeSpec]:
  """Return the default local-bridge specifications."""
  return [
    BridgeSpec(
      service_key="postgres",
      public_host_env_key="POSTGRES_PUBLIC_HOST",
      local_port=postgres_port,
      purpose="PostgreSQL local TCP listener for DBeaver-style clients",
    ),
    BridgeSpec(
      service_key="neo4j",
      public_host_env_key="NEO4J_BOLT_PUBLIC_HOST",
      local_port=neo4j_port,
      purpose="Neo4j Bolt local TCP listener for Bolt drivers",
    ),
  ]


def bridge_state(spec: BridgeSpec, env: dict[str, str]) -> dict[str, Any]:
  """Return structured operator-facing details for one local bridge."""
  return {
    "service_key": spec.service_key,
    "public_host": env[spec.public_host_env_key],
    "local_host": LOCALHOST,
    "local_port": spec.local_port,
    "purpose": spec.purpose,
  }


def verify_postgres_bridge(local_port: int, env: dict[str, str]) -> dict[str, Any]:
  """Verify PostgreSQL connectivity through the Python bridge."""
  psycopg = get_psycopg_module()
  with psycopg.connect(
    host=LOCALHOST,
    port=local_port,
    dbname=env["POSTGRES_DB"],
    user=env["POSTGRES_USER"],
    password=env["POSTGRES_PASSWORD"],
    connect_timeout=10,
    sslmode="disable",
  ) as connection:
    with connection.cursor() as cursor:
      cursor.execute("SELECT 1")
      value = cursor.fetchone()[0]

  return {
    "ok": value == 1,
    "host": LOCALHOST,
    "port": local_port,
    "query_result": value,
  }


def verify_neo4j_bridge(local_port: int, env: dict[str, str]) -> dict[str, Any]:
  """Verify Neo4j Bolt connectivity through the Python bridge."""
  graph_database = get_graph_database_class()
  driver = graph_database.driver(
    f"bolt://{LOCALHOST}:{local_port}",
    auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
    connection_timeout=10,
  )
  try:
    with driver.session() as session:
      value = session.run("RETURN 1 AS ready").single()["ready"]
  finally:
    driver.close()

  return {
    "ok": value == 1,
    "host": LOCALHOST,
    "port": local_port,
    "query_result": value,
  }
