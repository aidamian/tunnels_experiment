#!/bin/bash
set -Eeuo pipefail

# This service script owns the Neo4j database container and the two tunnel
# processes that expose it. It keeps those processes alive until the
# top-level orchestrator stops the stack.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/../lib/common.sh"

scope="neo4j-service"
container_name="neo4j-demo"
ready_file="${RAW_LOGS_DIR}/${RUN_TS}_neo4j_service_ready.json"
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
  log_with_scope "${scope}" "starting Neo4j database container"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${container_name}" \
    -e "NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}" \
    -e "NEO4J_server_memory_heap_initial__size=256m" \
    -e "NEO4J_server_memory_heap_max__size=256m" \
    -e "NEO4J_server_memory_pagecache_size=256m" \
    -p 127.0.0.1:17474:7474 \
    -p 127.0.0.1:17687:7687 \
    neo4j:5.26-community >/dev/null
}

wait_for_ready() {
  wait_until "${scope}" "Neo4j cypher-shell" 60 3 \
    docker exec "${container_name}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" "RETURN 1 AS ready;"

  docker exec "${container_name}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "CREATE CONSTRAINT experiment_run_id IF NOT EXISTS FOR (n:ExperimentRun) REQUIRE n.runId IS UNIQUE;" >/dev/null
  docker exec "${container_name}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "CREATE CONSTRAINT experiment_event_id IF NOT EXISTS FOR (n:ExperimentEvent) REQUIRE n.eventId IS UNIQUE;" >/dev/null
  docker exec "${container_name}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "MERGE (client:BoltClient {name:'external-bolt-app'}) SET client.updatedAt=datetime();" >/dev/null
}

start_tunnels() {
  local https_pid
  local bolt_pid

  https_pid="$(start_tunnel_process "${scope}" "neo4j_https_tunnel" "${NEO4J_HTTP_TUNNEL_TOKEN}" "http://127.0.0.1:17474")"
  bolt_pid="$(start_tunnel_process "${scope}" "neo4j_bolt_tunnel" "${NEO4J_BOLT_TUNNEL_TOKEN}" "tcp://127.0.0.1:17687")"

  managed_pids+=("${https_pid}" "${bolt_pid}")
}

write_ready_file() {
  jq -n \
    --arg run_id "${RUN_TS}" \
    --arg container_name "${container_name}" \
    --arg http_origin "127.0.0.1:17474" \
    --arg bolt_origin "127.0.0.1:17687" \
    --arg public_http_host "${NEO4J_HTTP_PUBLIC_HOST}" \
    --arg public_bolt_host "${NEO4J_BOLT_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      service: "neo4j",
      container_name: $container_name,
      local_origins_inside_dind_host: {
        https: $http_origin,
        bolt: $bolt_origin
      },
      public_hosts: {
        https: $public_http_host,
        bolt: $public_bolt_host
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
  start_tunnels
  write_ready_file
  log_with_scope "${scope}" "Neo4j service startup complete"
  supervise
}

main "$@"
