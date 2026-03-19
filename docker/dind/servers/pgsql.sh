#!/bin/bash
set -Eeuo pipefail

# This service script owns the PostgreSQL database container and its tunnel.
# It prepares the proof table used by the host-side experiment and then
# supervises both the database container and the tunnel process.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/../lib/common.sh"

scope="pgsql-service"
container_name="postgres-demo"
ready_file="${RAW_LOGS_DIR}/${RUN_TS}_pgsql_service_ready.json"
managed_pids=()

cleanup() {
  local exit_code=$?
  set +e
  log_with_scope "${scope}" "cleanup started with exit code ${exit_code}"

  local pid
  for pid in "${managed_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

start_container() {
  log_with_scope "${scope}" "starting PostgreSQL database container"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${container_name}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -p 127.0.0.1:15432:5432 \
    postgres:17-alpine >/dev/null
}

wait_for_ready() {
  wait_until "${scope}" "PostgreSQL readiness" 60 2 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${container_name}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
  wait_until "${scope}" "PostgreSQL SQL interface" 30 1 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${container_name}" \
      psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT 1" -tA

  docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${container_name}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE IF NOT EXISTS tunnel_run_events (
          id bigserial PRIMARY KEY,
          run_id text NOT NULL,
          cycle integer NOT NULL,
          client_type text NOT NULL,
          proof text NOT NULL,
          observed_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (run_id, cycle, client_type)
        );" >/dev/null
}

start_tunnel() {
  local tunnel_pid
  tunnel_pid="$(start_tunnel_process "${scope}" "postgres_tunnel" "${POSTGRES_TUNNEL_TOKEN}" "tcp://127.0.0.1:15432")"
  managed_pids+=("${tunnel_pid}")
}

write_ready_file() {
  jq -n \
    --arg run_id "${RUN_TS}" \
    --arg container_name "${container_name}" \
    --arg local_origin "127.0.0.1:15432" \
    --arg public_host "${POSTGRES_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      service: "postgresql",
      container_name: $container_name,
      local_origin_inside_dind_host: $local_origin,
      public_host: $public_host,
      ready: true
    }' >"${ready_file}"
}

supervise() {
  while true; do
    if ! docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null | grep -q true; then
      log_with_scope "${scope}" "database container ${container_name} is no longer running"
      docker logs "${container_name}" | tail -n 200 >&2 || true
      return 1
    fi

    local pid
    for pid in "${managed_pids[@]}"; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        log_with_scope "${scope}" "managed process ${pid} exited unexpectedly"
        return 1
      fi
    done

    sleep 5
  done
}

main() {
  start_container
  wait_for_ready
  start_tunnel
  write_ready_file
  log_with_scope "${scope}" "PostgreSQL service startup complete"
  supervise
}

main "$@"
