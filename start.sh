#!/usr/bin/env bash
set -Eeuo pipefail

# start.sh is the single-command experiment entrypoint.
# It prepares runtime files, builds the DinD-host topology, runs the host-side
# consumer flow, writes logs, and tears the stack down unless --keep-up is set.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw_logs_dir="${repo_root}/_logs/raw"
venv_dir="${repo_root}/.venv"
duration_seconds=""
keep_up="false"
stack_started="false"
run_ts="unknown"

mkdir -p "${raw_logs_dir}"

usage() {
  cat <<'EOF'
Usage: ./start.sh [--duration-seconds N] [--keep-up]

Options:
  --duration-seconds N  Override the total host-side experiment duration.
  --keep-up             Leave the Compose stack running after the experiment finishes.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration-seconds)
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
  printf '[%s] [start.sh] %s\n' "$(date -Iseconds)" "$1"
}

run_with_log() {
  local label="$1"
  local logfile="$2"
  shift 2
  log "${label}"
  "$@" > >(tee "${logfile}") 2>&1
}

cleanup() {
  local exit_code=$?
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

  run_with_log \
    "installing host Python requirements" \
    "${raw_logs_dir}/bootstrap_pip.log" \
    "${venv_dir}/bin/pip" install -r "${repo_root}/requirements-host.txt"
}

cd "${repo_root}"

run_with_log "preparing runtime" "${raw_logs_dir}/prepare_runtime.log" python3 scripts/prepare_runtime.py
source "${repo_root}/.runtime/tunnels.env"
run_ts="${RUN_TS}"

ensure_python_env

run_with_log "validating compose configuration" "${raw_logs_dir}/${run_ts}_compose_config.log" docker compose config -q
run_with_log "building and starting the stack" "${raw_logs_dir}/${run_ts}_compose_up.log" docker compose up --build -d
stack_started="true"
run_with_log "waiting for the DinD-host topology" "${raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 scripts/wait_for_stack.py --run-ts "${run_ts}"

experiment_cmd=("${venv_dir}/bin/python" "${repo_root}/scripts/run_experiment.py" "--run-ts" "${run_ts}")
if [[ -n "${duration_seconds}" ]]; then
  experiment_cmd+=("--duration-seconds" "${duration_seconds}")
fi

run_with_log "running the host-side experiment" "${raw_logs_dir}/${run_ts}_experiment_console.log" "${experiment_cmd[@]}"
run_with_log "running the smoke test" "${raw_logs_dir}/${run_ts}_smoke_test.log" python3 scripts/smoke_test.py --run-ts "${run_ts}"
run_with_log "capturing compose status" "${raw_logs_dir}/${run_ts}_compose_ps.log" docker compose ps
run_with_log "capturing top-level container logs" "${raw_logs_dir}/${run_ts}_compose_logs.log" docker compose logs --no-color dind-host-container
run_with_log "appending run log" "${raw_logs_dir}/${run_ts}_append_runlog.log" python3 scripts/append_runlog.py --run-ts "${run_ts}"
run_with_log "writing iteration summary" "${raw_logs_dir}/${run_ts}_write_summary.log" python3 scripts/write_summary.py --run-ts "${run_ts}"

log "experiment ${run_ts} completed successfully"
