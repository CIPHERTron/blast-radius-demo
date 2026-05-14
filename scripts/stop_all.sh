#!/usr/bin/env bash
# Stop all 4 services using their pidfiles.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

echo "Stopping blast-radius-demo services..."
for entry in "checkout:8000" "inventory:8001" "payment:8002" "notification:8003"; do
  svc="${entry%%:*}"
  port="${entry##*:}"
  if [[ -f "$(pidfile "$svc")" ]]; then
    pid="$(cat "$(pidfile "$svc")" 2>/dev/null || echo "?")"
    echo "  stopping $svc (pid $pid, :$port)"
  else
    echo "  stopping $svc (:$port)"
  fi
  stop_service "$svc" "$port"
done

echo "All stopped."
