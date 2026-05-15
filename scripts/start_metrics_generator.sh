#!/usr/bin/env bash
# Start the PIPA metrics generator on port 8090.
#
#   ./scripts/start_metrics_generator.sh
#
# Env overrides:
#   PUSHGATEWAY_URL       default http://8.229.139.162:9091
#   PUSH_INTERVAL_SECONDS default 5
#   JOB_NAME              default blast-radius-demo
#   INSTANCE              default sim-0
#   PORT                  default 8090
#   DRY_RUN=1             skip Pushgateway pushes (useful for local dev)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GEN_DIR="$REPO_ROOT/metrics-generator"

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python)"
fi

# Install generator deps if prometheus-client is missing.
if ! "$PYTHON" -c "import prometheus_client" 2>/dev/null; then
  echo "[start] installing metrics-generator deps..."
  "$PYTHON" -m pip install -r "$GEN_DIR/requirements.txt"
fi

PORT="${PORT:-8090}"

echo "[start] PIPA metrics generator -> http://localhost:$PORT/"
echo "[start] pushgateway: ${PUSHGATEWAY_URL:-http://8.229.139.162:9091}"

cd "$GEN_DIR"
exec "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
