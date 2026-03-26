#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
client_root="${repo_root}/clients"
server_root="${repo_root}/servers"
client_raw_logs_dir="${client_root}/_logs/raw"
server_raw_logs_dir="${server_root}/_logs/raw"
venv_dir="${client_root}/.venv"
persistent_service_volume_name="tunnels-experiment-persistent-service-data"
duration_seconds=""
keep_up="false"
server_services="neo4j,pgsql"
stack_started="false"
cleanup_started="false"
run_ts="unknown"
compose_cmd=(docker compose --project-directory "${server_root}" -f "${server_root}/docker-compose.yml")

mkdir -p "${client_raw_logs_dir}" "${server_raw_logs_dir}"

usage() {
  cat <<'EOF'
Usage: ./start_e2e.sh [--duration-seconds N] [--server-services csv] [--keep-up]

Options:
  --duration-seconds N  Override the total host-side experiment duration.
  --server-services csv Comma-separated server services to launch inside dind-host-server.
  --keep-up             Leave the Compose stack running after the experiment finishes.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration-seconds)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --duration-seconds" >&2
        usage >&2
        exit 1
      fi
      duration_seconds="$2"
      shift 2
      ;;
    --keep-up)
      keep_up="true"
      shift
      ;;
    --server-services)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --server-services" >&2
        usage >&2
        exit 1
      fi
      server_services="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log() {
  local message="$1"
  local color="${2:-cyan}"
  local color_code=""
  case "${color}" in
    blue) color_code='\033[34m' ;;
    cyan) color_code='\033[36m' ;;
    green) color_code='\033[32m' ;;
    red) color_code='\033[31m' ;;
    yellow) color_code='\033[33m' ;;
  esac
  printf '%b[%s] [start_e2e.sh] %s\033[0m\n' "${color_code}" "$(date -Iseconds)" "${message}"
}

quoted_command() {
  printf '%q ' "$@"
}

run_step() {
  local label="$1"
  local logfile="$2"
  shift 2

  log "step: ${label}" blue
  log "logfile: ${logfile}" cyan
  log "command: $(quoted_command "$@")" yellow
  "$@" 2>&1 | tee "${logfile}"
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
  awk -F= '/^RUN_TS=/{print $2}' "${server_root}/.runtime/dind.env"
}

cleanup() {
  local exit_code=$?
  if [[ "${cleanup_started}" == "true" ]]; then
    return
  fi
  cleanup_started="true"
  if [[ "${stack_started}" == "true" && "${keep_up}" != "true" ]]; then
    log "stopping the Compose stack" yellow
    "${compose_cmd[@]}" down --remove-orphans --volumes \
      >"${server_raw_logs_dir}/${run_ts}_compose_down.log" 2>&1 || true
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
    "${client_raw_logs_dir}/bootstrap_pip.log" \
    "${venv_dir}/bin/pip" install -r "${client_root}/requirements.txt"
}

cd "${repo_root}"

run_step "preparing server runtime" "${server_raw_logs_dir}/prepare_runtime.log" python3 "${server_root}/src/utils/prepare_runtime.py" --enabled-services "${server_services}"
run_ts="$(extract_run_ts)"
if [[ -z "${run_ts}" ]]; then
  echo "failed to extract RUN_TS from servers/.runtime/dind.env" >&2
  exit 1
fi

ensure_python_env
ensure_persistent_service_volume

run_step "validating compose configuration" "${server_raw_logs_dir}/${run_ts}_compose_config.log" "${compose_cmd[@]}" config -q
run_step "building and starting the stack" "${server_raw_logs_dir}/${run_ts}_compose_up.log" "${compose_cmd[@]}" up --build -d
stack_started="true"

run_step "waiting for the DinD-host topology" "${server_raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 "${server_root}/src/utils/wait_for_stack.py" --run-ts "${run_ts}"

experiment_cmd=("${venv_dir}/bin/python" "${client_root}/src/experiment_runner.py" "--run-ts" "${run_ts}")
if [[ -n "${duration_seconds}" ]]; then
  experiment_cmd+=("--duration-seconds" "${duration_seconds}")
fi

run_step "running the host-side experiment" "${client_raw_logs_dir}/${run_ts}_experiment_console.log" "${experiment_cmd[@]}"
run_step "running the smoke test" "${client_raw_logs_dir}/${run_ts}_smoke_test.log" python3 "${client_root}/src/utils/smoke_test.py" --run-ts "${run_ts}"

run_step "capturing compose status" "${server_raw_logs_dir}/${run_ts}_compose_ps.log" "${compose_cmd[@]}" ps
run_step "capturing top-level container logs" "${server_raw_logs_dir}/${run_ts}_compose_logs.log" "${compose_cmd[@]}" logs --no-color dind-host-server
run_step "appending run log" "${client_raw_logs_dir}/${run_ts}_append_runlog.log" python3 "${client_root}/src/utils/append_runlog.py" --run-ts "${run_ts}"
run_step "writing iteration summary" "${client_raw_logs_dir}/${run_ts}_write_summary.log" python3 "${client_root}/src/utils/write_summary.py" --run-ts "${run_ts}"

log "experiment ${run_ts} completed successfully" green
