#!/bin/bash
set -Eeuo pipefail

# The orchestrator owns the overall startup order. It launches the service
# scripts, waits for each one to publish its ready marker, and then keeps the
# full DinD host alive while the service scripts supervise their own workloads.

base_dir="/opt/tunnel-demo"
source "${base_dir}/lib/common.sh"

service_pids=()

cleanup() {
  local exit_code=$?
  set +e
  log_with_scope "orchestrator" "cleanup started with exit code ${exit_code}"

  for pid in "${service_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

start_service_script() {
  local service_name="$1"
  local script_path="${base_dir}/servers/${service_name}.sh"
  local logfile="${RAW_LOGS_DIR}/${RUN_TS}_${service_name}_service_console.log"

  log_with_scope "orchestrator" "starting ${service_name} service script"
  "${script_path}" > >(tee -a "${logfile}") 2>&1 &
  service_pids+=("$!")
}

wait_for_service_markers() {
  wait_until "orchestrator" "Neo4j service marker" 90 2 test -f "${RAW_LOGS_DIR}/${RUN_TS}_neo4j_service_ready.json"
  wait_until "orchestrator" "PostgreSQL service marker" 90 2 test -f "${RAW_LOGS_DIR}/${RUN_TS}_pgsql_service_ready.json"
}

wait_for_local_origins() {
  wait_until "orchestrator" "Neo4j HTTPS origin port" 60 2 nc -z 127.0.0.1 17474
  wait_until "orchestrator" "Neo4j Bolt origin port" 60 2 nc -z 127.0.0.1 17687
  wait_until "orchestrator" "PostgreSQL origin port" 60 2 nc -z 127.0.0.1 15432
}

write_topology_ready_file() {
  jq -n \
    --arg run_id "${RUN_TS}" \
    --arg neo4j_http "https://${NEO4J_HTTP_PUBLIC_HOST}" \
    --arg neo4j_bolt "${NEO4J_BOLT_PUBLIC_HOST}" \
    --arg postgres_tcp "${POSTGRES_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      all_ready: true,
      published_ports_on_top_level_container: [],
      topology: {
        top_level_service: "dind-host-container",
        managed_service_containers: ["neo4j-demo", "postgres-demo"],
        local_origin_ports_inside_dind_host: {
          neo4j_https: "127.0.0.1:17474",
          neo4j_bolt: "127.0.0.1:17687",
          postgres_tcp: "127.0.0.1:15432"
        },
        tunnel_targets: {
          neo4j_https: $neo4j_http,
          neo4j_bolt: $neo4j_bolt,
          postgres_tcp: $postgres_tcp
        }
      }
    }' >"${RAW_LOGS_DIR}/${RUN_TS}_topology_ready.json"
}

supervise() {
  while true; do
    local pid
    for pid in "${service_pids[@]}"; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        log_with_scope "orchestrator" "service supervisor process ${pid} exited unexpectedly"
        return 1
      fi
    done

    sleep 5
  done
}

main() {
  start_service_script "neo4j"
  start_service_script "pgsql"

  wait_for_service_markers
  wait_for_local_origins
  log_with_scope "orchestrator" "tunnel 4 remains reserved and intentionally unused"
  write_topology_ready_file
  log_with_scope "orchestrator" "topology startup complete"
  supervise
}

main "$@"
