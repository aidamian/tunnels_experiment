#!/bin/bash
set -Eeuo pipefail

# This service script owns the full Neo4j slice of the demo:
# 1. start the Neo4j child container inside the DinD host;
# 2. wait until Neo4j accepts authenticated Cypher queries;
# 3. start the HTTP and Bolt tunnels that point at loopback-only origins inside
#    dind-host-container;
# 4. publish a generic ready marker that the orchestrator can consume without
#    any Neo4j-specific hard-coding.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/../lib/common.sh"

scope="neo4j-service"
service_key="neo4j"
container_name="neo4j-demo"
image_name="neo4j:5.26-community"
data_dir="$(persistent_service_dir "${service_key}")"
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
  # Remove any stale child container first so the current run has a clean and
  # deterministic starting point.
  log_with_scope "${scope}" "starting Neo4j database container"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  prepare_persistent_bind_dir "${data_dir}" "${image_name}" "neo4j"

  if [[ -d "${data_dir}/databases" ]]; then
    log_with_scope "${scope}" "reusing persisted Neo4j data from ${data_dir}"
  else
    log_with_scope "${scope}" "initializing new Neo4j data directory at ${data_dir}"
  fi

  # These binds target 127.0.0.1 inside dind-host-container, not the real
  # machine. That means only local processes inside the DinD host, such as
  # cloudflared, can reach the service directly.
  docker run -d \
    --name "${container_name}" \
    -v "${data_dir}:/data" \
    -e "NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}" \
    -e "NEO4J_server_memory_heap_initial__size=256m" \
    -e "NEO4J_server_memory_heap_max__size=256m" \
    -e "NEO4J_server_memory_pagecache_size=256m" \
    -p 127.0.0.1:17474:7474 \
    -p 127.0.0.1:17687:7687 \
    "${image_name}" >/dev/null
}

wait_for_ready() {
  # Do not expose the service publicly until we can execute authenticated Cypher
  # commands successfully inside the child container.
  wait_until "${scope}" "Neo4j cypher-shell" 60 3 \
    docker exec "${container_name}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" "RETURN 1 AS ready;"

  # Seed the minimal schema/data required by the host-side proof workload.
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

  # Tunnel 1 is ordinary HTTP proxying: Cloudflare receives HTTPS traffic from
  # the client side and forwards it to the local Neo4j HTTP origin.
  https_pid="$(start_tunnel_process "${scope}" "neo4j_https_tunnel" "${NEO4J_HTTP_TUNNEL_TOKEN}" "http://127.0.0.1:17474")"

  # Tunnel 2 is TCP mode. The public side still uses a Cloudflare hostname, but
  # the payload carried through that hostname is the raw Bolt TCP stream.
  bolt_pid="$(start_tunnel_process "${scope}" "neo4j_bolt_tunnel" "${NEO4J_BOLT_TUNNEL_TOKEN}" "tcp://127.0.0.1:17687")"

  managed_pids+=("${https_pid}" "${bolt_pid}")
}

write_ready_file() {
  jq -n \
    --arg run_id "${RUN_TS}" \
    --arg service_key "${service_key}" \
    --arg service_name "Neo4j" \
    --arg container_name "${container_name}" \
    --arg http_origin "127.0.0.1:17474" \
    --arg bolt_origin "127.0.0.1:17687" \
    --arg public_http_host "${NEO4J_HTTP_PUBLIC_HOST}" \
    --arg public_bolt_host "${NEO4J_BOLT_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      service_key: $service_key,
      service_name: $service_name,
      container_name: $container_name,
      local_origins: [
        {
          name: "neo4j_https",
          bind: $http_origin,
          origin_scheme: "http",
          purpose: "Neo4j Browser and HTTP API"
        },
        {
          name: "neo4j_bolt",
          bind: $bolt_origin,
          origin_scheme: "tcp",
          purpose: "Neo4j Bolt"
        }
      ],
      local_origin_map: {
        neo4j_https: $http_origin,
        neo4j_bolt: $bolt_origin
      },
      public_endpoints: [
        {
          name: "neo4j_https",
          hostname: $public_http_host,
          client_transport: "https",
          origin_scheme: "http",
          purpose: "Public HTTPS hostname that proxies to the Neo4j HTTP origin"
        },
        {
          name: "neo4j_bolt",
          hostname: $public_bolt_host,
          client_transport: "wss",
          origin_scheme: "tcp",
          purpose: "Public hostname used as a WebSocket carrier for the Bolt TCP stream"
        }
      ],
      public_host_map: {
        neo4j_https: $public_http_host,
        neo4j_bolt: $public_bolt_host
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
  log_with_scope "${scope}" "Neo4j service startup complete and ready marker written to ${ready_file}"
  supervise
}

main "$@"
