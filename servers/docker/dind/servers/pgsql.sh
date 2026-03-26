#!/bin/bash
set -Eeuo pipefail

# This service script owns the PostgreSQL slice of the demo:
# 1. start the PostgreSQL child container inside the DinD host;
# 2. wait for process-level and SQL-level readiness;
# 3. create the proof table used by the host-side experiment;
# 4. start the Cloudflare TCP tunnel that points at PostgreSQL's loopback-only
#    origin inside dind-host-server;
# 5. publish a generic ready marker for the orchestrator.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/../lib/common.sh"

scope="pgsql-service"
service_key="pgsql"
container_name="postgres-demo"
image_name="postgres:17-alpine"
data_dir="$(persistent_service_dir "postgres")"
ready_file="$(ready_file_for_service "${service_key}")"
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
  # Remove any stale child container first so the new run starts from a clean
  # PostgreSQL state.
  log_with_scope "${scope}" "starting PostgreSQL database container"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  prepare_persistent_bind_dir "${data_dir}" "${image_name}" "postgres"

  if [[ -f "${data_dir}/PG_VERSION" ]]; then
    log_with_scope "${scope}" "reusing persisted PostgreSQL data from ${data_dir}"
  else
    log_with_scope "${scope}" "initializing new PostgreSQL data directory at ${data_dir}"
  fi

  # This loopback bind lives inside dind-host-server only. The real machine
  # never receives a directly published PostgreSQL port from this child.
  docker run -d \
    --name "${container_name}" \
    -e "PGDATA=/var/lib/postgresql/data/pgdata" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -v "${data_dir}:/var/lib/postgresql/data/pgdata" \
    -p 127.0.0.1:15432:5432 \
    "${image_name}" >/dev/null
}

wait_for_ready() {
  # First wait for PostgreSQL's own readiness probe, then prove the SQL
  # interface works before we create the table used by the experiment.
  wait_until "${scope}" "PostgreSQL readiness" 60 2 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${container_name}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
  wait_until "${scope}" "PostgreSQL SQL interface" 30 1 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${container_name}" \
      psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT 1" -tA

  # The host-side workload writes one proof row per cycle. The uniqueness
  # constraint keeps reruns idempotent for the same run_id/cycle/client_type.
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

  # Tunnel 3 runs in Cloudflare TCP mode. The client-facing side uses a
  # WebSocket transport to carry the PostgreSQL byte stream.
  tunnel_pid="$(start_tunnel_process "${scope}" "postgres_tunnel" "${POSTGRES_TUNNEL_TOKEN}" "tcp://127.0.0.1:15432")"
  managed_pids+=("${tunnel_pid}")
}

write_ready_file() {
  jq -n \
    --arg run_id "${RUN_TS}" \
    --arg service_key "${service_key}" \
    --arg service_name "PostgreSQL" \
    --arg container_name "${container_name}" \
    --arg local_origin "127.0.0.1:15432" \
    --arg public_host "${POSTGRES_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      service_key: $service_key,
      service_name: $service_name,
      container_name: $container_name,
      local_origins: [
        {
          name: "postgres_tcp",
          bind: $local_origin,
          origin_scheme: "tcp",
          purpose: "PostgreSQL"
        }
      ],
      local_origin_map: {
        postgres_tcp: $local_origin
      },
      public_endpoints: [
        {
          name: "postgres_tcp",
          hostname: $public_host,
          client_transport: "wss",
          origin_scheme: "tcp",
          purpose: "Public hostname used as a WebSocket carrier for the PostgreSQL TCP stream"
        }
      ],
      public_host_map: {
        postgres_tcp: $public_host
      },
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
  log_with_scope "${scope}" "PostgreSQL service startup complete and ready marker written to ${ready_file}"
  supervise
}

main "$@"
