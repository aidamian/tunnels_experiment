"""Small ANSI-aware console logging helpers for app-side Python tools."""

from __future__ import annotations

from datetime import datetime, timezone


RESET = "\033[0m"
COLORS = {
  "blue": "\033[34m",
  "cyan": "\033[36m",
  "green": "\033[32m",
  "red": "\033[31m",
  "yellow": "\033[33m",
}


def colorize(message: str, color: str) -> str:
  return f"{COLORS.get(color, '')}{message}{RESET if color in COLORS else ''}"


def format_line(scope: str, message: str) -> str:
  timestamp = datetime.now(timezone.utc).isoformat()
  return f"[{timestamp}] [{scope}] {message}"
