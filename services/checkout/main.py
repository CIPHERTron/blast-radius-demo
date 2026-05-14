"""Checkout Service - the main orchestrator.

This is the upstream service that the dashboard (and ultimately the user)
talks to. It coordinates a 3-step transaction across the downstream
services:

    1. POST /reserve   on Inventory
    2. POST /charge    on Payment
    3. POST /send      on Notification    <- skipped by the broken build
       POST /commit    on Inventory       <- skipped by the broken build
       POST /confirm   on Payment         <- skipped by the broken build

When SERVICE_VERSION is the bad build (BROKEN=1) we crash between step 2
and step 3. Inventory is left holding a reservation, Payment is left
holding a captured-but-not-confirmed charge, Notification never fires.
That is the blast radius.
"""

from __future__ import annotations

import os
import sys
import uuid
import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Allow running this file directly via `python services/checkout/main.py`
# OR as a uvicorn module. Both need this path tweak so the sibling
# config.py can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    BROKEN,
    DOWNSTREAMS,
    INVENTORY_URL,
    NOTIFICATION_URL,
    PAYMENT_URL,
    SERVICE_NAME,
    SERVICE_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
SCRIPTS_DIR = REPO_ROOT / "scripts"


class CartItem(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class CheckoutRequest(BaseModel):
    customer: str = "alice@example.com"
    cart: List[CartItem] = Field(
        default_factory=lambda: [
            CartItem(sku="SKU-TSHIRT", qty=1),
            CartItem(sku="SKU-STICKER", qty=2),
        ]
    )
    amount: float = Field(default=29.99, gt=0)


class DeployRequest(BaseModel):
    version: Literal["good", "bad"]


# Per-process order log (cleared when checkout restarts - which is realistic;
# the inventory and payment state survives across restarts because they live
# in different services).
StepStatus = Literal["pending", "ok", "failed", "skipped"]


orders: List[Dict] = []


app = FastAPI(title="Checkout Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _new_order_record(req: CheckoutRequest, order_id: str) -> Dict:
    return {
        "order_id": order_id,
        "customer": req.customer,
        "cart": [item.model_dump() for item in req.cart],
        "amount": round(req.amount, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkout_version": SERVICE_VERSION,
        "broken_build": BROKEN,
        "steps": {
            "reserve": "pending",
            "charge": "pending",
            "notify": "pending",
            "commit": "pending",
            "confirm": "pending",
        },
        "status": "pending",
        "error": None,
    }


@app.get("/health")
def health():
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "ok",
        "broken_build": BROKEN,
        "downstreams": DOWNSTREAMS,
    }


@app.get("/state")
def state():
    blast_radius = {
        "stuck_orders": sum(
            1 for o in orders if o["status"] == "blast_radius"
        ),
        "successful_orders": sum(
            1 for o in orders if o["status"] == "success"
        ),
    }
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "broken_build": BROKEN,
        "orders": list(reversed(orders))[:50],
        "order_count": len(orders),
        "blast_radius": blast_radius,
    }


@app.post("/checkout")
async def checkout(req: CheckoutRequest):
    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    record = _new_order_record(req, order_id)
    orders.append(record)

    timeout = httpx.Timeout(5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # ---- Step 1: reserve inventory --------------------------------
        try:
            r = await client.post(
                f"{INVENTORY_URL}/reserve",
                json={
                    "order_id": order_id,
                    "items": [item.model_dump() for item in req.cart],
                },
            )
            r.raise_for_status()
            record["steps"]["reserve"] = "ok"
        except Exception as exc:
            record["steps"]["reserve"] = "failed"
            record["status"] = "failed"
            record["error"] = f"inventory.reserve: {exc}"
            raise HTTPException(status_code=502, detail=record["error"]) from exc

        # ---- Step 2: charge payment -----------------------------------
        try:
            r = await client.post(
                f"{PAYMENT_URL}/charge",
                json={
                    "order_id": order_id,
                    "customer": req.customer,
                    "amount": req.amount,
                },
            )
            r.raise_for_status()
            record["steps"]["charge"] = "ok"
        except Exception as exc:
            record["steps"]["charge"] = "failed"
            record["status"] = "failed"
            record["error"] = f"payment.charge: {exc}"
            # Compensate: release the reservation we just took.
            try:
                await client.post(
                    f"{INVENTORY_URL}/release", json={"order_id": order_id}
                )
            except Exception:
                pass
            raise HTTPException(status_code=502, detail=record["error"]) from exc

        # ===============================================================
        #  THE BLAST RADIUS
        # ===============================================================
        # The "broken" build of v1.0.1 has a bug here. It fails AFTER the
        # customer has been charged and inventory has been reserved, but
        # BEFORE notification, commit, or confirm have been called.
        # No compensating actions run. Inventory is stuck, payment is
        # orphaned, the customer never hears back.
        if BROKEN:
            record["steps"]["notify"] = "skipped"
            record["steps"]["commit"] = "skipped"
            record["steps"]["confirm"] = "skipped"
            record["status"] = "blast_radius"
            record["error"] = (
                f"checkout v{SERVICE_VERSION} crashed after charge: "
                "NullPointerException in OrderConfirmationHandler.send()"
            )
            raise HTTPException(status_code=500, detail=record["error"])
        # ===============================================================

        # ---- Step 3a: send notification -------------------------------
        try:
            r = await client.post(
                f"{NOTIFICATION_URL}/send",
                json={
                    "order_id": order_id,
                    "customer": req.customer,
                    "type": "order_confirmation",
                },
            )
            r.raise_for_status()
            record["steps"]["notify"] = "ok"
        except Exception as exc:
            record["steps"]["notify"] = "failed"
            # We'll still try to commit + confirm; notification failure is
            # non-fatal in our model (real-world: queue retry).
            record["error"] = f"notification.send: {exc}"

        # ---- Step 3b: commit inventory --------------------------------
        try:
            r = await client.post(
                f"{INVENTORY_URL}/commit", json={"order_id": order_id}
            )
            r.raise_for_status()
            record["steps"]["commit"] = "ok"
        except Exception as exc:
            record["steps"]["commit"] = "failed"
            record["error"] = (record["error"] or "") + f" inventory.commit: {exc}"

        # ---- Step 3c: confirm payment ---------------------------------
        try:
            r = await client.post(
                f"{PAYMENT_URL}/confirm", json={"order_id": order_id}
            )
            r.raise_for_status()
            record["steps"]["confirm"] = "ok"
        except Exception as exc:
            record["steps"]["confirm"] = "failed"
            record["error"] = (record["error"] or "") + f" payment.confirm: {exc}"

    record["status"] = (
        "success"
        if all(
            record["steps"][s] == "ok"
            for s in ("reserve", "charge", "notify", "commit", "confirm")
        )
        else "partial"
    )

    return {
        "order_id": order_id,
        "status": record["status"],
        "steps": record["steps"],
        "checkout_version": SERVICE_VERSION,
    }


# ---------------------------------------------------------------------------
#  Admin: simulate a deploy by re-execing this process with a different env.
# ---------------------------------------------------------------------------
@app.post("/admin/deploy")
async def deploy(req: DeployRequest):
    """Simulate a deploy by shelling out to scripts/deploy_{good,bad}.sh.

    The script kills this process and restarts uvicorn with new env vars.
    From the dashboard's perspective, /health goes red briefly, then comes
    back with a new version number.
    """
    script = SCRIPTS_DIR / (
        "deploy_good.sh" if req.version == "good" else "deploy_bad.sh"
    )
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"script not found: {script}")

    async def _run_deploy():
        # Small delay so the HTTP response can flush before we get nuked.
        await asyncio.sleep(0.3)
        subprocess.Popen(
            ["bash", str(script)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    asyncio.create_task(_run_deploy())

    return JSONResponse(
        {
            "status": "deploying",
            "target_version": "1.0.1-broken" if req.version == "bad" else "1.0.0",
            "previous_version": SERVICE_VERSION,
        }
    )


@app.post("/admin/reset")
async def reset_all():
    """Clear local order log AND ask each downstream to reset its state."""
    orders.clear()
    results: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
        for name, url in DOWNSTREAMS.items():
            try:
                r = await client.post(f"{url}/admin/reset")
                r.raise_for_status()
                results[name] = "ok"
            except Exception as exc:
                results[name] = f"error: {exc}"
    return {"status": "reset", "downstreams": results}


# ---------------------------------------------------------------------------
#  Static dashboard - mounted last so /api routes win.
# ---------------------------------------------------------------------------
if DASHBOARD_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(DASHBOARD_DIR), html=True),
        name="dashboard",
    )
