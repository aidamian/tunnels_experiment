#!/bin/bash
set -Eeuo pipefail

role="${DIND_ROLE:?DIND_ROLE is required}"
logs_dir="${LOGS_DIR:-/logs}"
run_ts="${RUN_TS:-$(date +%y%m%d_%H%M%S)}"
log_prefix="${run_ts}_${role}"

mkdir -p "${logs_dir}"

export DOCKER_HOST="${DOCKER_HOST:-tcp://127.0.0.1:2375}"

managed_pids=()
child_container=""

log() {
  local message="$1"
  printf '[%s] [%s] %s\n' "$(date -Iseconds)" "${role}" "${message}" | tee -a "${logs_dir}/${log_prefix}_role.log" >&2
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
  if [[ -n "${child_container}" ]]; then
    docker rm -f "${child_container}" >/dev/null 2>&1 || true
  fi
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
  log "starting nested Docker daemon"
  dockerd-entrypoint.sh --storage-driver=vfs --tls=false --host=unix:///var/run/docker.sock --host=tcp://0.0.0.0:2375 \
    >"${logs_dir}/${log_prefix}_dockerd.log" 2>&1 &
  managed_pids+=("$!")
  wait_until "nested Docker daemon" 60 2 sh -lc "curl -fsS http://127.0.0.1:2375/_ping | grep -q OK"
}

start_tunnel() {
  local name="$1"
  local token="$2"
  local url="$3"
  local logfile="${logs_dir}/${run_ts}_${name}.log"

  log "starting tunnel ${name} -> ${url}"
  cloudflared tunnel --no-autoupdate --loglevel info run --token "${token}" --url "${url}" \
    >"${logfile}" 2>&1 &
  local pid=$!
  managed_pids+=("${pid}")
  sleep 2
  if ! kill -0 "${pid}" 2>/dev/null; then
    log "tunnel ${name} exited immediately"
    tail -n 50 "${logfile}" >&2 || true
    return 1
  fi
}

run_neo4j_role() {
  child_container="neo4j-demo"
  log "starting Neo4j child container"
  docker rm -f "${child_container}" >/dev/null 2>&1 || true
  docker run -d --name "${child_container}" \
    -e "NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}" \
    -e "NEO4J_server_memory_heap_initial__size=256m" \
    -e "NEO4J_server_memory_heap_max__size=256m" \
    -e "NEO4J_server_memory_pagecache_size=256m" \
    -p 127.0.0.1:17474:7474 \
    -p 127.0.0.1:17687:7687 \
    neo4j:5.26-community >/dev/null

  wait_until "Neo4j child container" 60 3 \
    docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" "RETURN 1 AS ready;"

  docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "CREATE CONSTRAINT tunnel_demo_name IF NOT EXISTS FOR (n:TunnelDemo) REQUIRE n.name IS UNIQUE;" >/dev/null
  docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "MERGE (a:TunnelDemo {name:'neo4j-https'}) SET a.protocol='https', a.updatedAt=datetime();
     MERGE (b:TunnelDemo {name:'neo4j-bolt'}) SET b.protocol='bolt', b.updatedAt=datetime();" >/dev/null

  start_tunnel "neo4j_https_tunnel" "${NEO4J_HTTP_TUNNEL_TOKEN}" "http://127.0.0.1:17474"
  start_tunnel "neo4j_bolt_tunnel" "${NEO4J_BOLT_TUNNEL_TOKEN}" "tcp://127.0.0.1:17687"
}

run_postgres_role() {
  child_container="postgres-demo"
  log "starting PostgreSQL child container"
  docker rm -f "${child_container}" >/dev/null 2>&1 || true
  docker run -d --name "${child_container}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -p 127.0.0.1:15432:5432 \
    postgres:17-alpine >/dev/null

  wait_until "PostgreSQL child container" 60 2 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${child_container}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
  wait_until "PostgreSQL SQL interface" 20 1 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${child_container}" \
      psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT 1" -tA

  docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${child_container}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE IF NOT EXISTS tunnel_demo_items (id integer PRIMARY KEY, label text NOT NULL, observed_at timestamptz NOT NULL DEFAULT now());" \
    -c "INSERT INTO tunnel_demo_items (id, label) VALUES (1, 'postgres-tunnel-ok'), (2, 'cloudflare-tcp-ok') ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label;" \
    >/dev/null

  start_tunnel "postgres_tunnel" "${POSTGRES_TUNNEL_TOKEN}" "tcp://127.0.0.1:15432"
}

start_cluster_snapshot_loop() {
  (
    while true; do
      {
        printf '\n[%s] master cluster snapshot\n' "$(date -Iseconds)"
        docker -H tcp://embedded-neo4j:2375 ps --format 'embedded-neo4j {{.Names}} {{.Status}}' 2>/dev/null || echo "embedded-neo4j unavailable"
        docker -H tcp://embedded-postgres:2375 ps --format 'embedded-postgres {{.Names}} {{.Status}}' 2>/dev/null || echo "embedded-postgres unavailable"
      } >>"${logs_dir}/${run_ts}_master_cluster_snapshot.log"
      sleep 30
    done
  ) &
  managed_pids+=("$!")
}

run_master_role() {
  child_container="consumer-demo"
  log "waiting for embedded Docker APIs"
  wait_until "embedded-neo4j Docker API" 60 2 sh -lc "curl -fsS http://embedded-neo4j:2375/_ping | grep -q OK"
  wait_until "embedded-postgres Docker API" 60 2 sh -lc "curl -fsS http://embedded-postgres:2375/_ping | grep -q OK"

  log "building consumer child image"
  docker build -t tunnel-demo-consumer:latest /workspace/docker/consumer \
    >"${logs_dir}/${run_ts}_master_consumer_build.log" 2>&1

  log "starting consumer child container"
  docker rm -f "${child_container}" >/dev/null 2>&1 || true
  docker run -d --name "${child_container}" \
    -p 127.0.0.1:18000:8000 \
    -e "CONSUMER_HTTP_PUBLIC_HOST=${CONSUMER_HTTP_PUBLIC_HOST}" \
    -e "NEO4J_HTTP_PUBLIC_HOST=${NEO4J_HTTP_PUBLIC_HOST}" \
    -e "NEO4J_BOLT_PUBLIC_HOST=${NEO4J_BOLT_PUBLIC_HOST}" \
    -e "POSTGRES_PUBLIC_HOST=${POSTGRES_PUBLIC_HOST}" \
    -e "NEO4J_USER=${NEO4J_USER}" \
    -e "NEO4J_PASSWORD=${NEO4J_PASSWORD}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    tunnel-demo-consumer:latest >/dev/null

  wait_until "consumer app" 60 2 curl -fsS http://127.0.0.1:18000/healthz

  start_tunnel "consumer_http_tunnel" "${CONSUMER_HTTP_TUNNEL_TOKEN}" "http://127.0.0.1:18000"
  start_cluster_snapshot_loop
}

supervise() {
  while true; do
    if ! docker inspect -f '{{.State.Running}}' "${child_container}" 2>/dev/null | grep -q true; then
      log "child container ${child_container} is no longer running"
      docker logs "${child_container}" | tail -n 200 >&2 || true
      return 1
    fi

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

  case "${role}" in
    neo4j)
      run_neo4j_role
      ;;
    postgres)
      run_postgres_role
      ;;
    master)
      run_master_role
      ;;
    *)
      log "unsupported DIND_ROLE: ${role}"
      return 1
      ;;
  esac

  log "role startup complete"
  supervise
}

main "$@"
