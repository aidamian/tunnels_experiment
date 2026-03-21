"""Helpers for manual localhost bridges backed by tunnel FQDNs.

This module contains bridge-specific support code used by the manual bridge
CLI. It stays in ``src/bridge`` because these helpers describe bridge-owned
concepts such as bridge specifications, localhost forwarding targets, and
protocol-level verification through the bridge path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.envfiles import load_public_hosts_file


LOCALHOST = "127.0.0.1"


@dataclass(frozen=True)
class BridgeSpec:
  """Describe one manual localhost bridge exposed by the client-side bridge CLI.

  Attributes
  ----------
  service_key:
    Short service identifier such as ``"postgres"`` or ``"neo4j"``.
  public_host_key:
    Key used to read the public hostname from ``.runtime/public_hosts.json``.
  local_port:
    Localhost TCP port exposed by the bridge.
  purpose:
    Human-readable description of why the bridge exists.

  Examples
  --------
  >>> BridgeSpec(
  ...   service_key="postgres",
  ...   public_host_key="postgres",
  ...   local_port=55432,
  ...   purpose="PostgreSQL local TCP listener for DBeaver-style clients",
  ... )
  BridgeSpec(service_key='postgres', public_host_key='postgres', local_port=55432, purpose='PostgreSQL local TCP listener for DBeaver-style clients')
  """

  service_key: str
  public_host_key: str
  local_port: int
  purpose: str


def repo_root() -> Path:
  """Return the repository root path.

  Returns
  -------
  Path
    Absolute repository root path.

  Examples
  --------
  >>> repo_root().name
  'tunnels_experiment'
  """

  return Path(__file__).resolve().parents[2]


def public_hosts_path() -> Path:
  """Return the generated public-host mapping path.

  Returns
  -------
  Path
    Absolute path to ``.runtime/public_hosts.json``.

  Examples
  --------
  >>> public_hosts_path().name
  'public_hosts.json'
  """

  return repo_root() / ".runtime" / "public_hosts.json"


def load_public_hosts() -> dict[str, str]:
  """Load the generated public-host mapping for host-side bridge clients.

  Returns
  -------
  dict[str, str]
    Mapping from logical service keys to public Cloudflare hostnames.

  Raises
  ------
  FileNotFoundError
    Raised when ``.runtime/public_hosts.json`` does not exist yet.

  Examples
  --------
  Run ``python3 src/utils/prepare_runtime.py`` first, then:

  >>> hosts = load_public_hosts()
  >>> sorted(hosts)
  ['neo4j_bolt', 'neo4j_http', 'postgres']
  """

  path = public_hosts_path()
  if not path.exists():
    raise FileNotFoundError(
      f"{path} does not exist. Run `python3 src/utils/prepare_runtime.py` first."
    )
  return load_public_hosts_file(path)


def default_specs(postgres_port: int, neo4j_port: int) -> list[BridgeSpec]:
  """Return the default manual bridge specifications.

  Parameters
  ----------
  postgres_port:
    Localhost port to expose for PostgreSQL clients.
  neo4j_port:
    Localhost port to expose for Neo4j Bolt clients.

  Returns
  -------
  list[BridgeSpec]
    Ordered bridge specification list for the supported manual services.

  Examples
  --------
  >>> [spec.service_key for spec in default_specs(55432, 57687)]
  ['postgres', 'neo4j']
  """

  return [
    BridgeSpec(
      service_key="postgres",
      public_host_key="postgres",
      local_port=postgres_port,
      purpose="PostgreSQL local TCP listener for DBeaver-style clients",
    ),
    BridgeSpec(
      service_key="neo4j",
      public_host_key="neo4j_bolt",
      local_port=neo4j_port,
      purpose="Neo4j Bolt local TCP listener for Bolt drivers",
    ),
  ]


def bridge_state(spec: BridgeSpec, public_hosts: dict[str, str]) -> dict[str, Any]:
  """Return operator-facing details for one started local bridge.

  Parameters
  ----------
  spec:
    Bridge specification describing the local port and public hostname key.
  public_hosts:
    Mapping loaded from ``.runtime/public_hosts.json``.

  Returns
  -------
  dict[str, Any]
    Structured bridge metadata used by the CLI for printing and verification.

  Examples
  --------
  >>> state = bridge_state(default_specs(55432, 57687)[0], {"postgres": "example.com"})
  >>> state["local_host"], state["local_port"]
  ('127.0.0.1', 55432)
  """

  return {
    "service_key": spec.service_key,
    "public_host": public_hosts[spec.public_host_key],
    "local_host": LOCALHOST,
    "local_port": spec.local_port,
    "purpose": spec.purpose,
  }
