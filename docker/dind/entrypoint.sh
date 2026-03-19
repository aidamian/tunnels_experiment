#!/bin/bash
set -Eeuo pipefail

# This is the top-level DinD host entrypoint. It starts the nested Docker
# daemon inside this container, waits until the Docker CLI can use it, and
# then hands off to the orchestration layer that brings up the demo services.

base_dir="/opt/tunnel-demo"
source "${base_dir}/lib/common.sh"

managed_pids=()

cleanup() {
  local exit_code=$?
  set +e
  log_with_scope "entrypoint" "cleanup started with exit code ${exit_code}"

  for pid in "${managed_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

start_dockerd() {
  log_with_scope "entrypoint" "starting nested Docker daemon"
  dockerd \
    --storage-driver=vfs \
    --host=unix:///var/run/docker.sock \
    --tls=false \
    >"${RAW_LOGS_DIR}/${RUN_TS}_dockerd.log" 2>&1 &
  managed_pids+=("$!")

  wait_until "entrypoint" "nested Docker daemon" 60 2 docker info
}

main() {
  local orchestrator_pid

  export DOCKER_HOST="unix:///var/run/docker.sock"
  export DOCKER_TLS_CERTDIR=""

  start_dockerd
  log_with_scope "entrypoint" "starting service orchestration"
  /usr/local/bin/tunnel-demo-orchestrator.sh "$@" &
  orchestrator_pid="$!"
  managed_pids+=("${orchestrator_pid}")
  wait "${orchestrator_pid}"
}

main "$@"
