"""Helpers for interrogating the top-level Docker runtime during server waits."""

from __future__ import annotations

import subprocess


def docker_status() -> str:
  """Return a human-readable Docker status string for the top-level container."""
  result = subprocess.run(
    ["docker", "ps", "--filter", "name=^/dind-host-container$", "--format", "{{.Status}}"],
    check=False,
    capture_output=True,
    text=True,
  )
  return result.stdout.strip() or "container not running yet"
