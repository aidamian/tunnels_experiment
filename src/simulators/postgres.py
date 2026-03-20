"""PostgreSQL proof workload for the host-side experiment."""

from __future__ import annotations

from typing import Any

from bridge.universal import LOCALHOST
from utils.demo_config import POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_USER
from utils.dependencies import get_psycopg_module


def run_postgres_cycle(run_id: str, cycle: int, proof: str, local_port: int) -> dict[str, Any]:
  """Run one PostgreSQL write/read proof cycle.

  Parameters
  ----------
  run_id:
    Current run identifier.
  cycle:
    Current proof cycle number.
  proof:
    Unique proof string for this cycle.
  local_port:
    Localhost TCP port exposed by the host-side PostgreSQL bridge.

  Returns
  -------
  dict[str, Any]
    Structured result including inserted-row metadata and all rows for the run.
  """
  psycopg = get_psycopg_module()

  # Simulate an external PostgreSQL client, such as DBeaver, by connecting to
  # the host-side local TCP bridge and performing a real write/read cycle.
  with psycopg.connect(
    host=LOCALHOST,
    port=local_port,
    dbname=POSTGRES_DB,
    user=POSTGRES_USER,
    password=POSTGRES_PASSWORD,
    connect_timeout=10,
    sslmode="disable",
  ) as connection:
    with connection.cursor() as cursor:
      cursor.execute(
        """
        INSERT INTO tunnel_run_events (run_id, cycle, client_type, proof)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (run_id, cycle, client_type)
        DO UPDATE SET proof = EXCLUDED.proof, observed_at = now()
        RETURNING id, observed_at::text
        """,
        (run_id, cycle, "dbeaver-sim", proof),
      )
      inserted_id, observed_at = cursor.fetchone()
      cursor.execute(
        """
        SELECT id, cycle, client_type, proof, observed_at::text
        FROM tunnel_run_events
        WHERE run_id = %s
        ORDER BY cycle, id
        """,
        (run_id,),
      )
      rows = [
        {
          "id": row[0],
          "cycle": row[1],
          "client_type": row[2],
          "proof": row[3],
          "observed_at": row[4],
        }
        for row in cursor.fetchall()
      ]
    connection.commit()

  return {
    "ok": True,
    "inserted_id": inserted_id,
    "inserted_at": observed_at,
    "rows_for_run": rows,
  }
