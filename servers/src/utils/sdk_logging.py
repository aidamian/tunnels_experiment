"""Helpers for operator-facing server-side logs emitted through the Ratio1 SDK logger."""

from __future__ import annotations

try:
  from ratio1 import Logger
except ModuleNotFoundError as exc:
  raise SystemExit("missing host dependency. Install the Ratio1 SDK for server-side Python utilities.") from exc


COLOR_MAP = {
  "blue": "b",
  "cyan": "c",
  "green": "g",
  "red": "r",
  "yellow": "y",
}


def build_console_logger(scope: str) -> Logger:
  """Return a quiet SDK logger for server-side console status updates."""
  return Logger(scope.upper(), no_folders_no_save=True, silent=True)


def log_message(logger: Logger, message: str, *, color: str | None = None, boxed: bool = False) -> None:
  """Emit one operator-facing message through a quiet SDK logger."""
  logger.P(message, color=COLOR_MAP.get(color, color), boxed=boxed, show=True)
