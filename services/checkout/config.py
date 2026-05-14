"""Checkout service configuration - read from environment variables."""

from __future__ import annotations

import os


SERVICE_NAME = "checkout"

SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "1.0.0")

# When BROKEN=1 we simulate a bad deployment: the orchestrator crashes
# AFTER charging the customer but BEFORE sending the confirmation, and
# without releasing the inventory reservation.
BROKEN = os.environ.get("BROKEN", "0") == "1"

INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://localhost:8001")
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://localhost:8002")
NOTIFICATION_URL = os.environ.get("NOTIFICATION_URL", "http://localhost:8003")

DOWNSTREAMS = {
    "inventory": INVENTORY_URL,
    "payment": PAYMENT_URL,
    "notification": NOTIFICATION_URL,
}
