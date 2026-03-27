"""Helpers for operator-facing logs emitted through the Ratio1 SDK logger."""

from __future__ import annotations

from pathlib import Path

try:
  from ratio1 import Logger
except ModuleNotFoundError as exc:
  raise SystemExit(
    "missing host dependency. Install clients/requirements.txt so Ratio1 SDK logging and bridge support are available."
  ) from exc


COLOR_MAP = {
  "blue": "b",
  "cyan": "c",
  "green": "g",
  "red": "r",
  "yellow": "y",
}
LOGGER_SUBDIRS = ("_data", "_logs", "_models", "_output")


def color_token(color: str | None) -> str | None:
  """Translate repository color names to Ratio1 SDK logger color tokens."""
  if color is None:
    return None
  return COLOR_MAP.get(color, color)


def build_console_logger(scope: str) -> Logger:
  """Return a quiet SDK logger for console-only status updates."""
  return Logger(scope.upper(), no_folders_no_save=True, silent=True)


def build_persistent_logger(scope: str, *, base_folder: Path, app_folder: str) -> tuple[Logger, Path]:
  """Return an SDK logger whose file output is rooted in the requested folder tree."""
  app_root = base_folder / app_folder
  for subdir in LOGGER_SUBDIRS:
    (app_root / subdir).mkdir(parents=True, exist_ok=True)

  logger = Logger(scope, base_folder=str(base_folder), app_folder=app_folder, silent=True)
  return logger, Path(logger.get_logs_folder()) / f"{scope}.txt"


def log_message(logger: Logger, message: str, *, color: str | None = None, boxed: bool = False) -> None:
  """Emit one operator-facing message through a quiet SDK logger."""
  logger.P(message, color=color_token(color), boxed=boxed, show=True)
