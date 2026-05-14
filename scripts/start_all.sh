#!/usr/bin/env bash
# Start all 4 services as background processes. Idempotent: if a pidfile
# exists and the process is alive, it is left alone.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

echo "Starting blast-radius-demo services..."
echo "  repo root: $REPO_ROOT"
echo "  python:    $PYTHON"
echo

# Stop any leftover processes from a previous run so ports are free.
# We pass the port too, so leftover listeners that aren't tracked by our
# pidfiles also get cleaned up.
stop_service inventory     8001
stop_service payment       8002
stop_service notification  8003
stop_service checkout      8000

start_service inventory     "services.inventory.main:app"     8001 "SERVICE_VERSION=1.0.0"
start_service payment       "services.payment.main:app"       8002 "SERVICE_VERSION=1.0.0"
start_service notification  "services.notification.main:app"  8003 "SERVICE_VERSION=1.0.0"

# Checkout starts in the healthy build by default.
start_service checkout "services.checkout.main:app" 8000 \
  "SERVICE_VERSION=1.0.0 BROKEN=0 INVENTORY_URL=http://localhost:8001 PAYMENT_URL=http://localhost:8002 NOTIFICATION_URL=http://localhost:8003"

echo
echo "Waiting for services to come online..."
all_ok=1
for entry in "inventory:8001" "payment:8002" "notification:8003" "checkout:8000"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  if wait_for_port "$port" && verify_owner "$name" "$port"; then
    echo "  $name :$port  ready"
  else
    echo "  $name :$port  FAILED - check $(logfile "$name")"
    all_ok=0
  fi
done

echo
if [[ "$all_ok" == "1" ]]; then
  echo "All services up."
  echo "  Dashboard:    http://localhost:8000/"
  echo "  Checkout API: http://localhost:8000/health"
  echo "  Inventory:    http://localhost:8001/state"
  echo "  Payment:      http://localhost:8002/state"
  echo "  Notification: http://localhost:8003/state"
  echo
  echo "Stop with: ./scripts/stop_all.sh"
else
  echo "WARNING: not all services started. Check logs/*.log."
  exit 1
fi
