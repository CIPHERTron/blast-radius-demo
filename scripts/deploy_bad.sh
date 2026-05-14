#!/usr/bin/env bash
# Restart ONLY the checkout service with the BROKEN build (v1.0.1-broken).
# This simulates a bad deploy: code that passes health checks but crashes
# halfway through the checkout transaction, leaving stuck inventory
# reservations and orphaned payment charges. That is the blast radius.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

echo "[deploy] Rolling out checkout v1.0.1-broken (BAD)..."
stop_service checkout 8000

start_service checkout "services.checkout.main:app" 8000 \
  "SERVICE_VERSION=1.0.1-broken BROKEN=1 INVENTORY_URL=http://localhost:8001 PAYMENT_URL=http://localhost:8002 NOTIFICATION_URL=http://localhost:8003"

if wait_for_port 8000 && verify_owner checkout 8000; then
  echo "[deploy] checkout v1.0.1-broken running on :8000 (it WILL fail real orders)"
else
  echo "[deploy] WARNING: checkout did not come up - see $(logfile checkout)"
  exit 1
fi
