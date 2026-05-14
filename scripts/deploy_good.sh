#!/usr/bin/env bash
# Restart ONLY the checkout service with the healthy build (v1.0.0).
# Inventory / payment / notification keep running - their state survives
# the redeploy, just like a real deploy.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

echo "[deploy] Rolling out checkout v1.0.0 (good)..."
stop_service checkout 8000

start_service checkout "services.checkout.main:app" 8000 \
  "SERVICE_VERSION=1.0.0 BROKEN=0 INVENTORY_URL=http://localhost:8001 PAYMENT_URL=http://localhost:8002 NOTIFICATION_URL=http://localhost:8003"

if wait_for_port 8000 && verify_owner checkout 8000; then
  echo "[deploy] checkout v1.0.0 healthy on :8000"
else
  echo "[deploy] WARNING: checkout did not come up - see $(logfile checkout)"
  exit 1
fi
