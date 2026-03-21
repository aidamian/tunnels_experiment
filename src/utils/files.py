"""File-writing helpers shared across host-side scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
  """Write JSON to disk atomically.

  Parameters
  ----------
  path:
    Target file path.
  payload:
    JSON-serializable dictionary to write.

  Returns
  -------
  None
    The target file is replaced atomically after the temporary file is written.

  Examples
  --------
  ``write_json_file(Path('_logs/raw/report.json'), {'all_ok': True})``
  """
  # Use a temporary file plus replace so readers never observe a half-written
  # JSON artifact while another script is still writing it.
  path.parent.mkdir(parents=True, exist_ok=True)
  temp_path = path.with_suffix(path.suffix + ".tmp")
  temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
  temp_path.replace(path)
