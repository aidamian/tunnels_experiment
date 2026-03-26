"""Helpers for interrogating the app DinD runtime during waits."""

from __future__ import annotations

import subprocess


def docker_status() -> str:
  result = subprocess.run(
    ["docker", "ps", "--filter", "name=^/dind-host-app$", "--format", "{{.Status}}"],
    check=False,
    capture_output=True,
    text=True,
  )
  return result.stdout.strip() or "container not running yet"
