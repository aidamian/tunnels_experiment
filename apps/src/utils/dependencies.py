"""Lazy imports for optional app-side Python dependencies."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


INSTALL_HINT = "missing app dependency inside dind-host-app"


def _import_required_module(module_name: str) -> ModuleType:
  try:
    return import_module(module_name)
  except ModuleNotFoundError as exc:
    raise SystemExit(INSTALL_HINT) from exc


def get_psycopg_module() -> ModuleType:
  return _import_required_module("psycopg")


def get_websocket_module() -> ModuleType:
  return _import_required_module("websocket")
