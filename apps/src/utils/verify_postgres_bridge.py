"""Verify PostgreSQL connectivity through the app-host bridge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
  sys.path.insert(0, str(SRC_DIR))

from utils.dependencies import get_psycopg_module
from utils.sdk_logging import build_console_logger, log_message


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Verify PostgreSQL connectivity through the app-host bridge.")
  parser.add_argument("--host", required=True)
  parser.add_argument("--port", required=True, type=int)
  parser.add_argument("--database", required=True)
  parser.add_argument("--user", required=True)
  parser.add_argument("--password", required=True)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  log = build_console_logger("apps-pg-verify")
  psycopg = get_psycopg_module()
  with psycopg.connect(
    host=args.host,
    port=args.port,
    dbname=args.database,
    user=args.user,
    password=args.password,
    connect_timeout=10,
    sslmode="disable",
  ) as connection:
    with connection.cursor() as cursor:
      cursor.execute("SELECT 1")
      value = cursor.fetchone()[0]

  log_message(log, f"postgres bridge verification result: {value}", color="green" if value == 1 else "red")
  return 0 if value == 1 else 1


if __name__ == "__main__":
  raise SystemExit(main())
