"""Helpers for generated host-side runtime files."""

from __future__ import annotations

import json
from pathlib import Path


def load_public_hosts_file(path: Path) -> dict[str, str]:
  """Parse the generated public-host mapping file.

  Parameters
  ----------
  path:
    Path to `.runtime/public_hosts.json`.

  Returns
  -------
  dict[str, str]
    Mapping of service keys to public hostnames.

  Examples
  --------
  >>> hosts = load_public_hosts_file(Path(".runtime/public_hosts.json"))
  >>> "postgres" in hosts
  True
  """
  payload = json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(payload, dict):
    raise ValueError(f"expected a JSON object in {path}")

  hosts: dict[str, str] = {}
  for key, value in payload.items():
    hosts[str(key)] = str(value)
  return hosts
