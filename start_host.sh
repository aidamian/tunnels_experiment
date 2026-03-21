#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw_logs_dir="${repo_root}/_logs/raw"
venv_dir="${repo_root}/.venv"
persistent_service_volume_name="tunnels-experiment-persistent-service-data"
stack_started="false"
cleanup_started="false"
run_ts="unknown"

mkdir -p "${raw_logs_dir}"

usage() {
  cat <<'EOF'
Usage: ./start_host.sh [start_local_bridges.py options]

This command starts the DinD stack, waits for readiness, and then launches the
manual Python bridge in the foreground for host tools such as DBeaver.

Examples:
  ./start_host.sh
  ./start_host.sh --service postgres
  ./start_host.sh --postgres-port 55440 --neo4j-port 57695
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

bridge_args=("$@")

log() {
  printf '[%s] [start_host.sh] %s\n' "$(date -Iseconds)" "$1"
}

quoted_command() {
  printf '%q ' "$@"
}

run_step() {
  local label="$1"
  local logfile="$2"
  shift 2

  log "step: ${label}"
  log "logfile: ${logfile}"
  log "command: $(quoted_command "$@")"
  "$@" 2>&1 | tee "${logfile}"
}

run_quiet_step() {
  local label="$1"
  local logfile="$2"
  shift 2

  log "step: ${label}"
  log "logfile: ${logfile}"
  log "command: $(quoted_command "$@")"
  log "streaming suppressed; see logfile for full command output"

  if ! "$@" >"${logfile}" 2>&1; then
    log "step failed; last 40 log lines:"
    tail -n 40 "${logfile}" >&2 || true
    return 1
  fi
}

ensure_persistent_service_volume() {
  if docker volume inspect "${persistent_service_volume_name}" >/dev/null 2>&1; then
    log "persistent service data volume ${persistent_service_volume_name} already exists"
    return
  fi

  log "creating persistent service data volume ${persistent_service_volume_name}"
  docker volume create "${persistent_service_volume_name}" >/dev/null
}

extract_run_ts() {
  awk -F= '/^RUN_TS=/{print $2}' "${repo_root}/.runtime/dind.env"
}

cleanup() {
  local exit_code=$?
  if [[ "${cleanup_started}" == "true" ]]; then
    return
  fi
  cleanup_started="true"
  if [[ "${stack_started}" == "true" ]]; then
    log "stopping the Compose stack"
    docker compose down --remove-orphans --volumes \
      >"${raw_logs_dir}/${run_ts}_compose_down.log" 2>&1 || true
  fi
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

ensure_python_env() {
  if [[ ! -x "${venv_dir}/bin/python" ]]; then
    log "creating local virtual environment"
    python3 -m venv "${venv_dir}"
  fi

  run_step \
    "installing host Python requirements" \
    "${raw_logs_dir}/bootstrap_pip.log" \
    "${venv_dir}/bin/pip" install -r "${repo_root}/requirements-host.txt"
}

cd "${repo_root}"

run_step "preparing runtime" "${raw_logs_dir}/prepare_runtime.log" python3 src/utils/prepare_runtime.py
run_ts="$(extract_run_ts)"
if [[ -z "${run_ts}" ]]; then
  echo "failed to extract RUN_TS from .runtime/dind.env" >&2
  exit 1
fi

ensure_python_env
ensure_persistent_service_volume

run_step "validating compose configuration" "${raw_logs_dir}/${run_ts}_compose_config.log" docker compose config -q
run_quiet_step "building and starting the stack" "${raw_logs_dir}/${run_ts}_compose_up.log" docker compose up --build -d
stack_started="true"

run_step "waiting for the DinD-host topology" "${raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 src/utils/wait_for_stack.py --run-ts "${run_ts}"

log "starting foreground Python bridge for host-side tools"
"${venv_dir}/bin/python" "${repo_root}/src/utils/start_local_bridges.py" --run-ts "${run_ts}" "${bridge_args[@]}"
