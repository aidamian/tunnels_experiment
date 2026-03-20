"""Helpers for loading topology metadata produced by the DinD orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_topology_snapshot(path: Path, env: dict[str, str]) -> dict[str, Any]:
  """Load the orchestrator's aggregated topology snapshot.

  Parameters
  ----------
  path:
    Path to `_logs/raw/<RUN_TS>_topology_ready.json`.
  env:
    Parsed runtime env file.

  Returns
  -------
  dict[str, Any]
    Topology payload. Falls back to the current expected topology if the file
    is missing or malformed.
  """
  # Fall back to the current expected demo topology when the generated snapshot
  # is unavailable, but prefer the snapshot so reports reflect the actual
  # service list started by the generic orchestrator.
  fallback = {
    "top_level_container": "dind-host-container",
    "top_level_service": "dind-host-container",
    "managed_service_containers": ["neo4j-demo", "postgres-demo"],
    "local_origins_inside_dind_host": {
      "neo4j_https": "127.0.0.1:17474",
      "neo4j_bolt": "127.0.0.1:17687",
      "postgres_tcp": "127.0.0.1:15432",
    },
    "public_hosts": {
      "neo4j_https": env["NEO4J_HTTP_PUBLIC_HOST"],
      "neo4j_bolt": env["NEO4J_BOLT_PUBLIC_HOST"],
      "postgres_tcp": env["POSTGRES_PUBLIC_HOST"],
    },
  }

  if not path.exists():
    return fallback

  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except json.JSONDecodeError:
    return fallback

  topology = payload.get("topology")
  if not isinstance(topology, dict):
    return fallback

  merged = dict(topology)
  merged.setdefault("top_level_service", "dind-host-container")
  merged.setdefault("top_level_container", merged["top_level_service"])
  merged.setdefault("managed_service_containers", fallback["managed_service_containers"])
  merged.setdefault("local_origins_inside_dind_host", fallback["local_origins_inside_dind_host"])
  merged.setdefault("public_hosts", fallback["public_hosts"])
  return merged
