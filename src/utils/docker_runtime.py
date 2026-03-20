"""Helpers for interrogating the top-level Docker runtime state."""

from __future__ import annotations

import json
import subprocess


def docker_status() -> str:
  """Return a human-readable Docker status string for the top-level container.

  Returns
  -------
  str
    Docker-reported container status, or a fallback message if absent.
  """
  # This helper keeps the polling scripts readable by centralizing the exact
  # `docker ps` filter used to locate `dind-host-container`.
  result = subprocess.run(
    ["docker", "ps", "--filter", "name=^/dind-host-container$", "--format", "{{.Status}}"],
    check=False,
    capture_output=True,
    text=True,
  )
  return result.stdout.strip() or "container not running yet"


def top_level_published_ports() -> list[str]:
  """Return actual host port bindings for the top-level DinD container.

  Returns
  -------
  list[str]
    Human-readable host-binding descriptions. Empty means nothing is published.
  """
  # `docker inspect` is the authoritative source for whether the top-level
  # container published any real host ports.
  result = subprocess.run(
    ["docker", "inspect", "dind-host-container", "--format", "{{json .NetworkSettings.Ports}}"],
    check=False,
    capture_output=True,
    text=True,
  )
  if result.returncode != 0 or not result.stdout.strip():
    return []

  payload = json.loads(result.stdout)
  published_ports: list[str] = []
  for container_port, bindings in payload.items():
    if not bindings:
      continue
    for binding in bindings:
      published_ports.append(f"{binding['HostIp']}:{binding['HostPort']}->{container_port}")
  return published_ports
