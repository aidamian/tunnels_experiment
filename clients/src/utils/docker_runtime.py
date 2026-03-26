"""Helpers for interrogating the top-level Docker runtime state."""

from __future__ import annotations

import json
import subprocess


TOP_LEVEL_CONTAINERS = ["dind-host-server", "dind-host-app"]


def docker_status() -> str:
  """Return a human-readable Docker status string for the top-level container.

  Returns
  -------
  str
    Docker-reported container status, or a fallback message if absent.

  Examples
  --------
  >>> isinstance(docker_status(), str)
  True
  """
  # This helper keeps the polling scripts readable by centralizing the exact
  # `docker ps` filter used to locate `dind-host-server`.
  result = subprocess.run(
    ["docker", "ps", "--filter", "name=^/dind-host-server$", "--format", "{{.Status}}"],
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

  Examples
  --------
  In the expected demo topology this returns an empty list because the
  top-level DinD container publishes no host ports.
  """
  # `docker inspect` is the authoritative source for whether the top-level
  # container published any real host ports.
  published_ports: list[str] = []
  for container_name in TOP_LEVEL_CONTAINERS:
    result = subprocess.run(
      ["docker", "inspect", container_name, "--format", "{{json .NetworkSettings.Ports}}"],
      check=False,
      capture_output=True,
      text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
      continue

    payload = json.loads(result.stdout)
    for container_port, bindings in payload.items():
      if not bindings:
        continue
      for binding in bindings:
        published_ports.append(f"{container_name}:{binding['HostIp']}:{binding['HostPort']}->{container_port}")
  return published_ports
