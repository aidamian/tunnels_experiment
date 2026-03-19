"""Helpers for the generated `.runtime/tunnels.env` file."""

from __future__ import annotations

from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
  """Parse the generated runtime env file.

  Parameters
  ----------
  path:
    Path to `.runtime/tunnels.env`.

  Returns
  -------
  dict[str, str]
    Parsed key-value pairs from the env file.
  """
  # The generated env file is intentionally simple `KEY=VALUE` syntax so the
  # host-side tools can parse it without depending on shell evaluation.
  values: dict[str, str] = {}
  for line in path.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      continue
    key, value = stripped.split("=", 1)
    values[key] = value
  return values
