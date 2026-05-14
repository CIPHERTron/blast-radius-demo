"""Notification Service - sends order confirmations.

Downstream of the Checkout service. Owns a log of sent notifications.
The blast-radius angle: when Checkout dies before calling /send, the
customer is silently left in the dark - no email, no SMS, no signal -
even though they were charged and inventory was reserved.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


SERVICE_NAME = "notification"
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "1.0.0")


class SendRequest(BaseModel):
    order_id: str
    customer: str
    type: str = "order_confirmation"
    message: Optional[str] = None


sent: List[Dict] = []


app = FastAPI(title="Notification Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "ok",
    }


@app.get("/state")
def state():
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "sent": sent,
        "sent_count": len(sent),
    }


@app.post("/send")
def send(req: SendRequest):
    record = {
        "notification_id": f"nt_{uuid.uuid4().hex[:10]}",
        "order_id": req.order_id,
        "customer": req.customer,
        "type": req.type,
        "message": req.message
        or f"Hi {req.customer}, your order {req.order_id} is confirmed!",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    sent.append(record)
    return record


@app.post("/admin/reset")
def reset():
    sent.clear()
    return {"status": "reset"}
