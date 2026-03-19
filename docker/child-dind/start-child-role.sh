#!/bin/bash
set -Eeuo pipefail

# This script runs inside a nested child DinD container.
# Each child owns one database family and publishes that database port
# only to the boundary of this child container.

role="${CHILD_ROLE:?CHILD_ROLE is required}"
logs_dir="${LOGS_DIR:-/logs}"
raw_logs_dir="${logs_dir}/raw"
run_ts="${RUN_TS:?RUN_TS is required}"
docker_host="${DOCKER_HOST:-tcp://127.0.0.1:2375}"
ready_file="${raw_logs_dir}/${run_ts}_${role}_child_ready.json"

mkdir -p "${raw_logs_dir}"
export DOCKER_HOST="${docker_host}"

managed_pids=()
child_container=""

log() {
  printf '[%s] [%s-child] %s\n' "$(date -Iseconds)" "${role}" "$1" | tee -a "${raw_logs_dir}/${run_ts}_${role}_child.log" >&2
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
  log "starting child nested Docker daemon"
  dockerd \
    --storage-driver=vfs \
    --tls=false \
    --host=unix:///var/run/docker.sock \
    --host=tcp://127.0.0.1:2375 \
    >"${raw_logs_dir}/${run_ts}_${role}_dockerd.log" 2>&1 &
  managed_pids+=("$!")

  wait_until "child nested Docker daemon" 60 2 sh -lc "curl -fsS http://127.0.0.1:2375/_ping | grep -q OK"
}

write_ready_file() {
  local inner_container_name="$1"
  local published_port="$2"

  jq -n \
    --arg run_id "${run_ts}" \
    --arg role "${role}" \
    --arg inner_container "${inner_container_name}" \
    --arg published_port "${published_port}" \
    '{
      run_id: $run_id,
      role: $role,
      inner_container: $inner_container,
      published_port_to_parent: $published_port,
      ready: true
    }' >"${ready_file}"
}

run_neo4j_role() {
  child_container="neo4j-demo"
  log "starting Neo4j inner database container"
  docker rm -f "${child_container}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${child_container}" \
    -e "NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}" \
    -e "NEO4J_server_memory_heap_initial__size=256m" \
    -e "NEO4J_server_memory_heap_max__size=256m" \
    -e "NEO4J_server_memory_pagecache_size=256m" \
    -p 0.0.0.0:17474:7474 \
    -p 0.0.0.0:17687:7687 \
    neo4j:5.26-community >/dev/null

  wait_until "Neo4j cypher-shell" 60 3 \
    docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" "RETURN 1 AS ready;"

  docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "CREATE CONSTRAINT experiment_run_id IF NOT EXISTS FOR (n:ExperimentRun) REQUIRE n.runId IS UNIQUE;" >/dev/null
  docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "CREATE CONSTRAINT experiment_event_id IF NOT EXISTS FOR (n:ExperimentEvent) REQUIRE n.eventId IS UNIQUE;" >/dev/null
  docker exec "${child_container}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
    "MERGE (client:BoltClient {name:'external-bolt-app'}) SET client.updatedAt=datetime();" >/dev/null

  write_ready_file "${child_container}" "17474,17687"
}

run_postgres_role() {
  child_container="postgres-demo"
  log "starting PostgreSQL inner database container"
  docker rm -f "${child_container}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${child_container}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -p 0.0.0.0:15432:5432 \
    postgres:17-alpine >/dev/null

  wait_until "PostgreSQL readiness" 60 2 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${child_container}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
  wait_until "PostgreSQL SQL interface" 30 1 \
    docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${child_container}" \
      psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT 1" -tA

  docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" "${child_container}" \
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

  write_ready_file "${child_container}" "15432"
}

supervise() {
  while true; do
    if ! docker inspect -f '{{.State.Running}}' "${child_container}" 2>/dev/null | grep -q true; then
      log "inner database container ${child_container} is no longer running"
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
    *)
      log "unsupported CHILD_ROLE: ${role}"
      return 1
      ;;
  esac

  log "child role startup complete"
  supervise
}

main "$@"
