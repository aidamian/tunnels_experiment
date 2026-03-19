#!/bin/bash
set -Eeuo pipefail

# This script runs inside the single top-level DinD host container.
# It starts two nested DinD child containers, waits for their databases
# to be reachable from the top-level private network, and only then starts
# the outbound Cloudflare Tunnel processes.

logs_dir="${LOGS_DIR:-/logs}"
raw_logs_dir="${logs_dir}/raw"
run_ts="${RUN_TS:?RUN_TS is required}"
docker_host="${DOCKER_HOST:-tcp://127.0.0.1:2375}"
child_image="tunnel-demo-child-dind:latest"
topology_ready_file="${raw_logs_dir}/${run_ts}_topology_ready.json"

mkdir -p "${raw_logs_dir}"
export DOCKER_HOST="${docker_host}"

managed_pids=()
managed_containers=()
neo4j_origin_host=""
postgres_origin_host=""

log() {
  local message="$1"
  printf '[%s] [dind-host] %s\n' "$(date -Iseconds)" "${message}" | tee -a "${raw_logs_dir}/${run_ts}_dind_host.log" >&2
}

cleanup() {
  local exit_code=$?
  set +e
  log "cleanup started with exit code ${exit_code}"

  for pid in "${managed_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  for container_name in "${managed_containers[@]:-}"; do
    docker rm -f "${container_name}" >/dev/null 2>&1 || true
  done

  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

wait_until() {
  local description="$1"
  local attempts="$2"
  local delay_seconds="$3"
  shift 3

  local try
  for ((try = 1; try <= attempts; try += 1)); do
    if "$@" >/dev/null 2>&1; then
      log "${description} is ready"
      return 0
    fi
    sleep "${delay_seconds}"
  done

  log "${description} failed readiness checks"
  return 1
}

start_dockerd() {
  log "starting top-level nested Docker daemon"
  dockerd \
    --storage-driver=vfs \
    --tls=false \
    --host=unix:///var/run/docker.sock \
    --host=tcp://127.0.0.1:2375 \
    >"${raw_logs_dir}/${run_ts}_dind_host_dockerd.log" 2>&1 &
  managed_pids+=("$!")

  wait_until "top-level nested Docker daemon" 60 2 sh -lc "curl -fsS http://127.0.0.1:2375/_ping | grep -q OK"
}

build_child_image() {
  log "building reusable nested child DinD image"
  docker build -t "${child_image}" /workspace/docker/child-dind \
    >"${raw_logs_dir}/${run_ts}_child_dind_build.log" 2>&1
}

ensure_network() {
  if ! docker network inspect nested-dind-mesh >/dev/null 2>&1; then
    log "creating private network for the child DinD containers"
    docker network create nested-dind-mesh >/dev/null
  fi
}

start_child_dind() {
  local role="$1"
  local container_name="$2"

  log "starting child DinD container ${container_name} for role ${role}"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${container_name}" \
    --privileged \
    --network nested-dind-mesh \
    --network-alias "${container_name}" \
    --entrypoint /bin/bash \
    -e "CHILD_ROLE=${role}" \
    -e "RUN_TS=${run_ts}" \
    -e "LOGS_DIR=/logs" \
    -e "DOCKER_HOST=tcp://127.0.0.1:2375" \
    -e "DOCKER_TLS_CERTDIR=" \
    -e "NEO4J_USER=${NEO4J_USER}" \
    -e "NEO4J_PASSWORD=${NEO4J_PASSWORD}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -v /workspace:/workspace:ro \
    -v /logs:/logs \
    "${child_image}" \
    /workspace/docker/child-dind/start-child-role.sh >/dev/null

  managed_containers+=("${container_name}")
}

wait_for_child_ready_markers() {
  wait_until "Neo4j child DinD ready marker" 60 2 test -f "${raw_logs_dir}/${run_ts}_neo4j_child_ready.json"
  wait_until "PostgreSQL child DinD ready marker" 60 2 test -f "${raw_logs_dir}/${run_ts}_postgres_child_ready.json"
}

resolve_child_origins() {
  neo4j_origin_host="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' neo4j-dind)"
  postgres_origin_host="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' postgres-dind)"

  if [[ -z "${neo4j_origin_host}" || -z "${postgres_origin_host}" ]]; then
    log "failed to resolve child DinD bridge IPs"
    return 1
  fi

  log "resolved neo4j-dind origin host to ${neo4j_origin_host}"
  log "resolved postgres-dind origin host to ${postgres_origin_host}"
}

wait_for_child_ports() {
  wait_until "Neo4j HTTPS origin port" 60 2 nc -z "${neo4j_origin_host}" 17474
  wait_until "Neo4j Bolt origin port" 60 2 nc -z "${neo4j_origin_host}" 17687
  wait_until "PostgreSQL origin port" 60 2 nc -z "${postgres_origin_host}" 15432
}

start_tunnel() {
  local tunnel_name="$1"
  local token="$2"
  local url="$3"
  local logfile="${raw_logs_dir}/${run_ts}_${tunnel_name}.log"

  log "starting tunnel ${tunnel_name} -> ${url}"
  cloudflared tunnel \
    --metrics 127.0.0.1:0 \
    --no-autoupdate \
    --loglevel info \
    run \
    --token "${token}" \
    --url "${url}" \
    >"${logfile}" 2>&1 &

  local pid=$!
  managed_pids+=("${pid}")
  sleep 3

  if ! kill -0 "${pid}" 2>/dev/null; then
    log "tunnel ${tunnel_name} exited immediately"
    tail -n 50 "${logfile}" >&2 || true
    return 1
  fi
}

write_topology_ready_file() {
  jq -n \
    --arg run_id "${run_ts}" \
    --arg neo4j_http "https://${NEO4J_HTTP_PUBLIC_HOST}" \
    --arg neo4j_bolt "${NEO4J_BOLT_PUBLIC_HOST}" \
    --arg postgres_tcp "${POSTGRES_PUBLIC_HOST}" \
    '{
      run_id: $run_id,
      all_ready: true,
      published_ports_on_top_level_container: [],
      topology: {
        top_level_service: "dind-host-container",
        child_dind_containers: ["neo4j-dind", "postgres-dind"],
        tunnel_targets: {
          neo4j_https: $neo4j_http,
          neo4j_bolt: $neo4j_bolt,
          postgres_tcp: $postgres_tcp
        }
      }
    }' >"${topology_ready_file}"
}

supervise() {
  while true; do
    for container_name in "${managed_containers[@]}"; do
      if ! docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null | grep -q true; then
        log "child DinD container ${container_name} is no longer running"
        docker logs "${container_name}" | tail -n 200 >&2 || true
        return 1
      fi
    done

    for pid in "${managed_pids[@]}"; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        log "managed process ${pid} exited unexpectedly"
        return 1
      fi
    done

    sleep 5
  done
}

main() {
  start_dockerd
  build_child_image
  ensure_network

  start_child_dind "neo4j" "neo4j-dind"
  start_child_dind "postgres" "postgres-dind"

  wait_for_child_ready_markers
  resolve_child_origins
  wait_for_child_ports

  start_tunnel "neo4j_https_tunnel" "${NEO4J_HTTP_TUNNEL_TOKEN}" "http://${neo4j_origin_host}:17474"
  start_tunnel "neo4j_bolt_tunnel" "${NEO4J_BOLT_TUNNEL_TOKEN}" "tcp://${neo4j_origin_host}:17687"
  start_tunnel "postgres_tunnel" "${POSTGRES_TUNNEL_TOKEN}" "tcp://${postgres_origin_host}:15432"

  log "tunnel 4 remains reserved and intentionally unused"
  write_topology_ready_file
  log "topology startup complete"
  supervise
}

main "$@"
