"""Payment Service - records charges and refunds.

Downstream of the Checkout service. Owns a simple ledger of charges.
A charge becomes "orphaned" when it has been captured but the upstream
Checkout never confirmed the order (i.e. the charge was never marked
confirmed and never refunded). Orphaned charges are real customer money
sitting in limbo - the most visible piece of the blast radius.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


SERVICE_NAME = "payment"
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "1.0.0")


class ChargeRequest(BaseModel):
    order_id: str
    customer: str
    amount: float = Field(gt=0)


class OrderRef(BaseModel):
    order_id: str


# order_id -> charge record
charges: Dict[str, dict] = {}


app = FastAPI(title="Payment Service")
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
    charge_list = list(charges.values())
    orphaned = [c for c in charge_list if c["status"] == "captured"]
    confirmed = [c for c in charge_list if c["status"] == "confirmed"]
    refunded = [c for c in charge_list if c["status"] == "refunded"]

    total_orphaned = round(sum(c["amount"] for c in orphaned), 2)
    total_confirmed = round(sum(c["amount"] for c in confirmed), 2)

    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "charges": charge_list,
        "orphaned_count": len(orphaned),
        "confirmed_count": len(confirmed),
        "refunded_count": len(refunded),
        "total_orphaned": total_orphaned,
        "total_confirmed": total_confirmed,
    }


@app.post("/charge")
def charge(req: ChargeRequest):
    if req.order_id in charges:
        raise HTTPException(status_code=409, detail="order already charged")

    record = {
        "charge_id": f"ch_{uuid.uuid4().hex[:10]}",
        "order_id": req.order_id,
        "customer": req.customer,
        "amount": round(req.amount, 2),
        "status": "captured",
        "charged_at": datetime.now(timezone.utc).isoformat(),
    }
    charges[req.order_id] = record
    return record


@app.post("/confirm")
def confirm(req: OrderRef):
    """Marks a charge as confirmed - the upstream order completed end-to-end."""
    if req.order_id not in charges:
        raise HTTPException(status_code=404, detail="no charge for order")
    charges[req.order_id]["status"] = "confirmed"
    charges[req.order_id]["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    return charges[req.order_id]


@app.post("/refund")
def refund(req: OrderRef):
    if req.order_id not in charges:
        raise HTTPException(status_code=404, detail="no charge for order")
    charges[req.order_id]["status"] = "refunded"
    charges[req.order_id]["refunded_at"] = datetime.now(timezone.utc).isoformat()
    return charges[req.order_id]


@app.post("/admin/reset")
def reset():
    charges.clear()
    return {"status": "reset"}
