#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw_logs_dir="${repo_root}/_logs/raw"
venv_dir="${repo_root}/.venv"
persistent_service_volume_name="tunnels-experiment-persistent-service-data"
duration_seconds=""
keep_up="false"
stack_started="false"
cleanup_started="false"
run_ts="unknown"

mkdir -p "${raw_logs_dir}"

usage() {
  cat <<'EOF'
Usage: ./start_e2e.sh [--duration-seconds N] [--keep-up]

Options:
  --duration-seconds N  Override the total host-side experiment duration.
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
  printf '[%s] [start_e2e.sh] %s\n' "$(date -Iseconds)" "$1"
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
  if [[ "${stack_started}" == "true" && "${keep_up}" != "true" ]]; then
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
run_step "building and starting the stack" "${raw_logs_dir}/${run_ts}_compose_up.log" docker compose up --build -d
stack_started="true"

run_step "waiting for the DinD-host topology" "${raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 src/utils/wait_for_stack.py --run-ts "${run_ts}"

experiment_cmd=("${venv_dir}/bin/python" "${repo_root}/src/experiment_runner.py" "--run-ts" "${run_ts}")
if [[ -n "${duration_seconds}" ]]; then
  experiment_cmd+=("--duration-seconds" "${duration_seconds}")
fi

run_step "running the host-side experiment" "${raw_logs_dir}/${run_ts}_experiment_console.log" "${experiment_cmd[@]}"
run_step "running the smoke test" "${raw_logs_dir}/${run_ts}_smoke_test.log" python3 src/utils/smoke_test.py --run-ts "${run_ts}"

run_step "capturing compose status" "${raw_logs_dir}/${run_ts}_compose_ps.log" docker compose ps
run_step "capturing top-level container logs" "${raw_logs_dir}/${run_ts}_compose_logs.log" docker compose logs --no-color dind-host-container
run_step "appending run log" "${raw_logs_dir}/${run_ts}_append_runlog.log" python3 src/utils/append_runlog.py --run-ts "${run_ts}"
run_step "writing iteration summary" "${raw_logs_dir}/${run_ts}_write_summary.log" python3 src/utils/write_summary.py --run-ts "${run_ts}"

log "experiment ${run_ts} completed successfully"
