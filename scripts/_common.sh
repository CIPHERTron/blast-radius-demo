#!/usr/bin/env bash
# Shared helpers for the start/stop/deploy scripts.

set -euo pipefail

# Resolve repo root regardless of where the script was invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

# Pick a Python interpreter. Prefer .venv if it exists.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  PYTHON="$(command -v python)"
fi

# pidfile / logfile paths for a given service.
pidfile() { echo "$LOG_DIR/$1.pid"; }
logfile() { echo "$LOG_DIR/$1.log"; }

# Kill any process listening on a TCP port. Uses lsof, falls back gracefully
# if lsof is missing.
kill_port() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -z "$pids" ]]; then return 0; fi
    sleep 0.2
  done
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  for pid in $pids; do
    kill -9 "$pid" 2>/dev/null || true
  done
}

# Stop a service: kill the pidfile process AND anything still on the port,
# so we never end up with a zombie listener masking a failed restart.
#   stop_service <name> [port]
stop_service() {
  local name="$1"
  local port="${2:-}"
  local pf
  pf="$(pidfile "$name")"
  if [[ -f "$pf" ]]; then
    local pid
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5; do
        if kill -0 "$pid" 2>/dev/null; then sleep 0.2; else break; fi
      done
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pf"
  fi
  if [[ -n "$port" ]]; then
    kill_port "$port"
  fi
}

# Start a uvicorn process for a given service.
#   start_service <name> <module> <port> [extra env "K=V K=V"]
start_service() {
  local name="$1"
  local module="$2"
  local port="$3"
  local extra_env="${4:-}"

  local pf
  pf="$(pidfile "$name")"
  local lf
  lf="$(logfile "$name")"

  cd "$REPO_ROOT"

  # Build env prefix.
  local env_prefix=""
  if [[ -n "$extra_env" ]]; then
    env_prefix="env $extra_env"
  fi

  # shellcheck disable=SC2086
  nohup $env_prefix "$PYTHON" -m uvicorn "$module" \
    --host 0.0.0.0 --port "$port" --log-level info \
    >>"$lf" 2>&1 &
  echo $! >"$pf"
  echo "  started $name (pid $(cat "$pf"), :$port) -> $lf"
}

wait_for_port() {
  local port="$1"
  local tries="${2:-40}"
  for _ in $(seq 1 "$tries"); do
    if (echo > "/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.15
  done
  return 1
}

# Verify the process listening on a port matches the pid in the pidfile.
# This catches the case where our new uvicorn died on bind error and the
# port is being held by some unrelated lingering process.
verify_owner() {
  local name="$1"
  local port="$2"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pf
  pf="$(pidfile "$name")"
  if [[ ! -f "$pf" ]]; then
    return 1
  fi
  local expected
  expected="$(cat "$pf")"
  local actual
  actual="$(lsof -ti tcp:"$port" 2>/dev/null | head -1 || true)"
  [[ -n "$actual" && "$actual" == "$expected" ]]
}
