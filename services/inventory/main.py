"""Inventory Service - tracks stock levels and reservations.

Downstream of the Checkout service. Owns:
  - stock: SKU -> available units
  - reservations: order_id -> {sku: qty} (held, not yet committed)

The blast-radius story for this service: when the Checkout orchestrator
crashes between /reserve and /commit (or /release), reservations stay
stuck forever. That stuck state is what the dashboard surfaces.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


SERVICE_NAME = "inventory"
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "1.0.0")


INITIAL_STOCK: Dict[str, int] = {
    "SKU-TSHIRT": 50,
    "SKU-MUG": 100,
    "SKU-HOODIE": 25,
    "SKU-STICKER": 500,
}


class CartItem(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class ReserveRequest(BaseModel):
    order_id: str
    items: List[CartItem]


class OrderRef(BaseModel):
    order_id: str


stock: Dict[str, int] = dict(INITIAL_STOCK)
reservations: Dict[str, Dict[str, int]] = {}
reservation_timestamps: Dict[str, str] = {}


app = FastAPI(title="Inventory Service")
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
    available = {sku: qty for sku, qty in stock.items()}
    reserved_totals: Dict[str, int] = {}
    for items in reservations.values():
        for sku, qty in items.items():
            reserved_totals[sku] = reserved_totals.get(sku, 0) + qty

    stuck_reservations = [
        {
            "order_id": oid,
            "items": items,
            "reserved_at": reservation_timestamps.get(oid),
        }
        for oid, items in reservations.items()
    ]

    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "stock": available,
        "reserved_totals": reserved_totals,
        "stuck_reservations": stuck_reservations,
        "stuck_reservation_count": len(stuck_reservations),
    }


@app.post("/reserve")
def reserve(req: ReserveRequest):
    if req.order_id in reservations:
        raise HTTPException(status_code=409, detail="order already reserved")

    for item in req.items:
        if item.sku not in stock:
            raise HTTPException(status_code=404, detail=f"unknown sku: {item.sku}")
        if stock[item.sku] < item.qty:
            raise HTTPException(
                status_code=409,
                detail=f"insufficient stock for {item.sku}: {stock[item.sku]} < {item.qty}",
            )

    for item in req.items:
        stock[item.sku] -= item.qty

    reservations[req.order_id] = {item.sku: item.qty for item in req.items}
    reservation_timestamps[req.order_id] = datetime.now(timezone.utc).isoformat()

    return {"order_id": req.order_id, "status": "reserved"}


@app.post("/commit")
def commit(req: OrderRef):
    if req.order_id not in reservations:
        raise HTTPException(status_code=404, detail="no reservation for order")
    del reservations[req.order_id]
    reservation_timestamps.pop(req.order_id, None)
    return {"order_id": req.order_id, "status": "committed"}


@app.post("/release")
def release(req: OrderRef):
    if req.order_id not in reservations:
        raise HTTPException(status_code=404, detail="no reservation for order")
    items = reservations.pop(req.order_id)
    reservation_timestamps.pop(req.order_id, None)
    for sku, qty in items.items():
        stock[sku] = stock.get(sku, 0) + qty
    return {"order_id": req.order_id, "status": "released"}


@app.post("/admin/reset")
def reset():
    stock.clear()
    stock.update(INITIAL_STOCK)
    reservations.clear()
    reservation_timestamps.clear()
    return {"status": "reset"}
