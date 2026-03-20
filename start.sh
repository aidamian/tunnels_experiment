#!/usr/bin/env bash
set -Eeuo pipefail

# start.sh is the single-command experiment entrypoint.
#
# It performs the entire documented flow in one place so a reader can follow
# the experiment from top to bottom without hunting through shell history:
# 1. generate runtime files from tunnels.json;
# 2. ensure the host-side Python environment exists;
# 3. validate and start the DinD stack;
# 4. wait for the in-container orchestrator to declare the topology ready;
# 5. run the host-side experiment and smoke test;
# 6. capture logs and write tracked summaries;
# 7. tear the stack down again unless --keep-up is requested.

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
  printf '[%s] [start.sh] %s\n' "$(date -Iseconds)" "$1"
}

quoted_command() {
  printf '%q ' "$@"
}

run_step() {
  local label="$1"
  local logfile="$2"
  shift 2

  # Each step logs three things explicitly:
  # - what is happening;
  # - where the full captured log will live;
  # - the exact command that is about to run.
  log "step: ${label}"
  log "logfile: ${logfile}"
  log "command: $(quoted_command "$@")"
  "$@" 2>&1 | tee "${logfile}"
}

cleanup() {
  local exit_code=$?

  # Always try to tear the stack down on exit unless the caller asked to keep
  # it running for manual inspection.
  if [[ "${stack_started}" == "true" && "${keep_up}" != "true" ]]; then
    log "stopping the Compose stack"
    docker compose down --remove-orphans --volumes \
      >"${raw_logs_dir}/${run_ts}_compose_down.log" 2>&1 || true
  fi
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

ensure_python_env() {
  # The host-side experiment runs outside Docker on purpose, so this helper
  # makes sure the local virtual environment exists and has the required
  # database/WebSocket dependencies installed.
  if [[ ! -x "${venv_dir}/bin/python" ]]; then
    log "creating local virtual environment"
    python3 -m venv "${venv_dir}"
  fi

  run_step \
    "installing host Python requirements" \
    "${raw_logs_dir}/bootstrap_pip.log" \
    "${venv_dir}/bin/pip" install -r "${repo_root}/requirements-host.txt"
}

# Work from the repository root so relative paths in the follow-up commands are
# stable and easy to understand from the logs.
cd "${repo_root}"

# Step 1: create `.runtime/tunnels.env` and the per-run timestamp. The
# host-side Python code now lives directly under `src/`.
run_step "preparing runtime" "${raw_logs_dir}/prepare_runtime.log" python3 src/utils/prepare_runtime.py
source "${repo_root}/.runtime/tunnels.env"
run_ts="${RUN_TS}"

# Step 2: ensure the host machine can run the experiment scripts directly.
ensure_python_env

# Step 3: validate and start the single top-level DinD container.
run_step "validating compose configuration" "${raw_logs_dir}/${run_ts}_compose_config.log" docker compose config -q
run_step "building and starting the stack" "${raw_logs_dir}/${run_ts}_compose_up.log" docker compose up --build -d
stack_started="true"

# Step 4: wait until the in-container orchestrator has started every service
# and written the topology_ready.json marker for this run.
run_step "waiting for the DinD-host topology" "${raw_logs_dir}/${run_ts}_wait_for_stack.log" python3 src/utils/wait_for_stack.py --run-ts "${run_ts}"

# Run the primary experiment entrypoint directly from the simplified source
# tree so the logs match the actual code layout.
experiment_cmd=("${venv_dir}/bin/python" "${repo_root}/src/experiment_runner.py" "--run-ts" "${run_ts}")
if [[ -n "${duration_seconds}" ]]; then
  experiment_cmd+=("--duration-seconds" "${duration_seconds}")
fi

# Step 5: run the host-side proof workload and validate the resulting report.
run_step "running the host-side experiment" "${raw_logs_dir}/${run_ts}_experiment_console.log" "${experiment_cmd[@]}"
run_step "running the smoke test" "${raw_logs_dir}/${run_ts}_smoke_test.log" python3 src/utils/smoke_test.py --run-ts "${run_ts}"

# Step 6: capture supporting evidence and update the tracked markdown logs.
run_step "capturing compose status" "${raw_logs_dir}/${run_ts}_compose_ps.log" docker compose ps
run_step "capturing top-level container logs" "${raw_logs_dir}/${run_ts}_compose_logs.log" docker compose logs --no-color dind-host-container
run_step "appending run log" "${raw_logs_dir}/${run_ts}_append_runlog.log" python3 src/utils/append_runlog.py --run-ts "${run_ts}"
run_step "writing iteration summary" "${raw_logs_dir}/${run_ts}_write_summary.log" python3 src/utils/write_summary.py --run-ts "${run_ts}"

log "experiment ${run_ts} completed successfully"
