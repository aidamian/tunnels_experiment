#!/bin/bash
set -Eeuo pipefail

# This is the top-level DinD host entrypoint.
#
# Its job is intentionally narrow:
# 1. start the nested Docker daemon inside dind-host-container;
# 2. wait until the Docker CLI can talk to that daemon;
# 3. hand control to the generic orchestrator that discovers and supervises the
#    child service scripts.

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
  # dockerd writes its own detailed log to a dedicated file so the main console
  # stream stays readable while preserving low-level diagnostics.
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

  # Force all nested Docker commands to use the private Unix socket inside this
  # container, never the real machine's Docker daemon.
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
