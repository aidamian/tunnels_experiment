"""Load the client-owned service catalog from ``clients/services.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOCALHOST = "127.0.0.1"


@dataclass(frozen=True)
class BridgeConfig:
  """Client-side local bridge settings for one tunnel-backed TCP service."""

  local_host: str
  local_port: int
  purpose: str


@dataclass(frozen=True)
class ServiceConfig:
  """One client-visible service entry from ``clients/services.json``."""

  key: str
  service: str
  type: str
  url: str
  bridge: BridgeConfig | None = None

  @property
  def public_host(self) -> str:
    """Return the normalized hostname used by HTTPS and websocket clients."""
    return normalize_public_host(self.url)

  @property
  def display_url(self) -> str:
    """Return a human-readable URL or hostname for operator output."""
    if self.type == "https":
      return self.url if self.url.startswith(("https://", "http://")) else f"https://{self.public_host}"
    return self.public_host

  def to_dict(self) -> dict[str, Any]:
    """Return a JSON-serializable dictionary for reports."""
    payload: dict[str, Any] = {
      "key": self.key,
      "service": self.service,
      "type": self.type,
      "url": self.url,
      "public_host": self.public_host,
    }
    if self.bridge is not None:
      payload["bridge"] = {
        "local_host": self.bridge.local_host,
        "local_port": self.bridge.local_port,
        "purpose": self.bridge.purpose,
      }
    return payload


def client_root() -> Path:
  """Return the absolute ``clients/`` directory path."""
  return Path(__file__).resolve().parents[2]


def services_path() -> Path:
  """Return the absolute path to ``clients/services.json``."""
  return client_root() / "services.json"


def normalize_public_host(raw_value: str) -> str:
  """Normalize a public service URL down to its hostname."""
  return (
    raw_value.strip()
    .removeprefix("https://")
    .removeprefix("http://")
    .removeprefix("wss://")
    .removeprefix("ws://")
    .rstrip("/")
  )


def load_services(path: Path | None = None) -> list[ServiceConfig]:
  """Parse the client-owned service catalog."""
  catalog_path = path or services_path()
  payload = json.loads(catalog_path.read_text(encoding="utf-8"))
  if not isinstance(payload, list):
    raise ValueError(f"expected a JSON list in {catalog_path}")

  services: list[ServiceConfig] = []
  seen_keys: set[str] = set()
  for entry in payload:
    if not isinstance(entry, dict):
      raise ValueError(f"invalid service entry in {catalog_path}: expected object")

    key = str(entry.get("key", "")).strip()
    service_name = str(entry.get("service", "")).strip()
    service_type = str(entry.get("type", "")).strip()
    url = str(entry.get("url", "")).strip()
    if not key or not service_name or not service_type or not url:
      raise ValueError(f"service entries in {catalog_path} require key/service/type/url")
    if key in seen_keys:
      raise ValueError(f"duplicate service key {key!r} in {catalog_path}")
    seen_keys.add(key)

    bridge_payload = entry.get("bridge")
    bridge: BridgeConfig | None = None
    if bridge_payload is not None:
      if not isinstance(bridge_payload, dict):
        raise ValueError(f"bridge config for {key!r} must be an object")
      local_host = str(bridge_payload.get("local_host", "")).strip() or LOCALHOST
      local_port = int(bridge_payload.get("local_port", 0))
      purpose = str(bridge_payload.get("purpose", "")).strip()
      if local_port <= 0 or not purpose:
        raise ValueError(f"bridge config for {key!r} requires local_port and purpose")
      bridge = BridgeConfig(local_host=local_host, local_port=local_port, purpose=purpose)

    services.append(
      ServiceConfig(
        key=key,
        service=service_name,
        type=service_type,
        url=url,
        bridge=bridge,
      ),
    )

  return services


def service_map(services: list[ServiceConfig]) -> dict[str, ServiceConfig]:
  """Index service catalog entries by stable key."""
  return {service.key: service for service in services}


def require_service(services: list[ServiceConfig], key: str) -> ServiceConfig:
  """Return one required service entry or raise a targeted error."""
  mapping = service_map(services)
  try:
    return mapping[key]
  except KeyError as exc:
    raise KeyError(f"service key {key!r} is missing from {services_path()}") from exc


def public_host_map(services: list[ServiceConfig]) -> dict[str, str]:
  """Return the public host mapping used in reports and summaries."""
  return {service.key: service.public_host for service in services}
