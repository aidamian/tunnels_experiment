"""Helpers for manual localhost bridges backed by ``clients/services.json``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.services import LOCALHOST, require_service, load_services


SERVICE_SELECTOR_MAP = {
  "postgres": "postgres",
  "neo4j": "neo4j_bolt",
  "neo4j_bolt": "neo4j_bolt",
}


@dataclass(frozen=True)
class BridgeSpec:
  """Describe one client-side localhost bridge."""

  service_key: str
  service_name: str
  public_host: str
  local_host: str
  local_port: int
  purpose: str


def client_root() -> Path:
  """Return the ``clients/`` directory path."""
  return Path(__file__).resolve().parents[2]


def default_specs(postgres_port: int | None, neo4j_port: int | None) -> list[BridgeSpec]:
  """Return bridge specifications from the client-owned service catalog."""
  services = load_services()
  postgres_service = require_service(services, "postgres")
  neo4j_service = require_service(services, "neo4j_bolt")
  if postgres_service.bridge is None or neo4j_service.bridge is None:
    raise ValueError("bridge-enabled services require a bridge section in clients/services.json")

  return [
    BridgeSpec(
      service_key="postgres",
      service_name=postgres_service.service,
      public_host=postgres_service.public_host,
      local_host=postgres_service.bridge.local_host,
      local_port=postgres_port or postgres_service.bridge.local_port,
      purpose=postgres_service.bridge.purpose,
    ),
    BridgeSpec(
      service_key="neo4j_bolt",
      service_name=neo4j_service.service,
      public_host=neo4j_service.public_host,
      local_host=neo4j_service.bridge.local_host,
      local_port=neo4j_port or neo4j_service.bridge.local_port,
      purpose=neo4j_service.bridge.purpose,
    ),
  ]


def bridge_state(spec: BridgeSpec) -> dict[str, Any]:
  """Return operator-facing details for one started local bridge."""
  return {
    "service_key": spec.service_key,
    "service_name": spec.service_name,
    "public_host": spec.public_host,
    "local_host": spec.local_host,
    "local_port": spec.local_port,
    "purpose": spec.purpose,
  }
