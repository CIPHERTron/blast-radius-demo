"""PIPA metrics generator - FastAPI control plane.

Run as a normal uvicorn app:
    PUSHGATEWAY_URL=http://8.229.139.162:9091 \
    python -m metrics-generator.main
or via the included start script. Open http://localhost:8090/ for the
dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# Make sibling modules importable when the file is run directly. uvicorn
# launched via `app_dir=metrics-generator/` already does this, but doing
# it here too means `python metrics-generator/main.py` works.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from state import ServiceState, ServiceTargets, health_label  # noqa: E402
from scenarios import (  # noqa: E402
    ALL_SERVICES,
    AUTO_TIMELINE,
    SCENARIOS,
    SCENARIO_DESCRIPTIONS,
    total_timeline_seconds,
)
from pusher import Pusher  # noqa: E402


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://8.229.139.162:9091")
JOB_NAME = os.environ.get("JOB_NAME", "blast-radius-demo")
INSTANCE = os.environ.get("INSTANCE", "sim-0")
PUSH_INTERVAL_SECONDS = float(os.environ.get("PUSH_INTERVAL_SECONDS", "5"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
PORT = int(os.environ.get("PORT", "8090"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("pipa-metrics-gen")


# ---------------------------------------------------------------------------
# Runtime state - kept simple, single-process
# ---------------------------------------------------------------------------


class Engine:
    def __init__(self) -> None:
        self.services: Dict[str, ServiceState] = {
            name: ServiceState(name=name) for name in ALL_SERVICES
        }
        self.current_scenario: str = "steady"
        self.last_push_results: Dict[str, str] = {}
        self.last_push_ts: float = 0.0
        self.tick_count: int = 0

        # Timeline driver state
        self.timeline_running: bool = False
        self.timeline_started_at: Optional[float] = None
        self.timeline_phase_idx: int = 0

        self.pusher = Pusher(
            pushgateway_url=PUSHGATEWAY_URL,
            job=JOB_NAME,
            instance=INSTANCE,
            dry_run=DRY_RUN,
        )

    # ----- scenario / timeline control -----

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise KeyError(name)
        self.current_scenario = name
        # Stopping any auto timeline if a manual switch happens.
        self.timeline_running = False
        self.timeline_started_at = None

    def start_timeline(self) -> None:
        self.timeline_running = True
        self.timeline_started_at = time.time()
        self.timeline_phase_idx = 0
        self.current_scenario = AUTO_TIMELINE[0].scenario

    def stop_timeline(self) -> None:
        self.timeline_running = False

    def reset(self) -> None:
        self.timeline_running = False
        self.timeline_started_at = None
        self.timeline_phase_idx = 0
        self.current_scenario = "steady"
        for s in self.services.values():
            s.reset()
        self.pusher.delete_all(self.services.keys())

    def _advance_timeline(self) -> None:
        if not self.timeline_running or self.timeline_started_at is None:
            return
        elapsed = time.time() - self.timeline_started_at
        cumulative = 0
        for idx, phase in enumerate(AUTO_TIMELINE):
            cumulative += phase.dwell_seconds
            if elapsed < cumulative:
                if self.current_scenario != phase.scenario:
                    log.info(
                        "[timeline] entering phase %d/%d: %s (dwell %ds)",
                        idx + 1,
                        len(AUTO_TIMELINE),
                        phase.scenario,
                        phase.dwell_seconds,
                    )
                self.current_scenario = phase.scenario
                self.timeline_phase_idx = idx
                return
        # Past the end of the timeline - stay on last phase but stop driver.
        last = AUTO_TIMELINE[-1]
        self.current_scenario = last.scenario
        self.timeline_phase_idx = len(AUTO_TIMELINE) - 1
        if self.timeline_running:
            log.info("[timeline] complete; holding on %s", last.scenario)
        self.timeline_running = False

    # ----- tick loop -----

    def tick(self) -> None:
        self._advance_timeline()
        targets = SCENARIOS[self.current_scenario]
        for name, state in self.services.items():
            t = targets.get(name)
            if t is None:
                continue
            state.tick(t)
        self.last_push_results = self.pusher.push_all(self.services.values())
        self.last_push_ts = time.time()
        self.tick_count += 1

    # ----- snapshots for the dashboard -----

    def snapshot(self) -> Dict:
        services = {n: s.snapshot() for n, s in self.services.items()}
        for n, snap in services.items():
            snap["health_label"] = health_label(snap["health"])
        timeline_total = total_timeline_seconds()
        if self.timeline_running and self.timeline_started_at:
            elapsed = time.time() - self.timeline_started_at
        else:
            elapsed = 0.0
        return {
            "scenario": self.current_scenario,
            "scenario_description": SCENARIO_DESCRIPTIONS.get(
                self.current_scenario, ""
            ),
            "timeline_running": self.timeline_running,
            "timeline_phase_idx": self.timeline_phase_idx,
            "timeline_phase_count": len(AUTO_TIMELINE),
            "timeline_elapsed_s": round(elapsed, 1),
            "timeline_total_s": timeline_total,
            "services": services,
            "last_push_ts": self.last_push_ts,
            "last_push_results": self.last_push_results,
            "tick_count": self.tick_count,
            "config": {
                "pushgateway_url": PUSHGATEWAY_URL,
                "job": JOB_NAME,
                "instance": INSTANCE,
                "push_interval_s": PUSH_INTERVAL_SECONDS,
                "dry_run": DRY_RUN,
            },
        }


engine = Engine()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


app = FastAPI(title="PIPA Metrics Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _start_loop() -> None:
    asyncio.create_task(_tick_loop())
    log.info(
        "metrics generator started: pushgateway=%s job=%s interval=%ss dry_run=%s",
        PUSHGATEWAY_URL,
        JOB_NAME,
        PUSH_INTERVAL_SECONDS,
        DRY_RUN,
    )


async def _tick_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(engine.tick)
        except Exception as exc:  # noqa: BLE001
            log.exception("tick loop error: %s", exc)
        await asyncio.sleep(PUSH_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/metrics", response_class=None)
def prometheus_metrics():
    """Prometheus scrape endpoint — exposes all 4 service series in a
    single response so Prometheus can scrape this pod directly, no
    Pushgateway required.

    Add this to prometheus.yml:

        - job_name: blast-radius-sim
          scrape_interval: 5s
          static_configs:
            - targets:
              - <this-pod-or-svc>:8090
    """
    from prometheus_client import generate_latest
    from starlette.responses import Response

    parts = []
    for svc in engine.services.values():
        reg = engine.pusher._build_registry(svc)  # noqa: SLF001
        parts.append(generate_latest(reg).decode("utf-8"))
    body = "\n".join(parts)
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/health")
def health() -> Dict:
    return {
        "status": "ok",
        "service": "metrics-generator",
        "scenario": engine.current_scenario,
        "tick_count": engine.tick_count,
    }


@app.get("/state")
def state() -> Dict:
    return engine.snapshot()


@app.get("/scenarios")
def list_scenarios() -> Dict:
    return {
        "scenarios": [
            {"name": name, "description": SCENARIO_DESCRIPTIONS.get(name, "")}
            for name in SCENARIOS.keys()
        ],
        "auto_timeline": [
            {"scenario": p.scenario, "dwell_seconds": p.dwell_seconds}
            for p in AUTO_TIMELINE
        ],
        "auto_timeline_total_seconds": total_timeline_seconds(),
    }


@app.post("/scenario/{name}")
def set_scenario(name: str) -> Dict:
    try:
        engine.set_scenario(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown scenario: {name}")
    return {
        "scenario": name,
        "description": SCENARIO_DESCRIPTIONS.get(name, ""),
    }


@app.post("/timeline/start")
def timeline_start() -> Dict:
    engine.start_timeline()
    return {
        "status": "started",
        "phases": len(AUTO_TIMELINE),
        "total_seconds": total_timeline_seconds(),
    }


@app.post("/timeline/stop")
def timeline_stop() -> Dict:
    engine.stop_timeline()
    return {"status": "stopped", "frozen_on": engine.current_scenario}


@app.post("/timeline/reset")
def timeline_reset() -> Dict:
    engine.reset()
    return {"status": "reset", "scenario": engine.current_scenario}


@app.get("/preview")
def preview() -> JSONResponse:
    """Per-service Prometheus exposition text for the current state.

    Useful for verifying the metric NAMES line up with what the PIPA
    agents query - paste this output into a PromQL playground or just
    eyeball the labels.
    """
    from prometheus_client import generate_latest

    out: Dict[str, str] = {}
    for svc in engine.services.values():
        reg = engine.pusher._build_registry(svc)  # noqa: SLF001 - private OK here
        out[svc.name] = generate_latest(reg).decode("utf-8")
    return JSONResponse(out)


# ---------------------------------------------------------------------------
# Static dashboard - mounted last so /api routes win.
# ---------------------------------------------------------------------------


_DASH = _HERE / "dashboard"
if _DASH.exists():
    app.mount("/", StaticFiles(directory=str(_DASH), html=True), name="dashboard")


# ---------------------------------------------------------------------------
# Direct-execution entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        app_dir=str(_HERE),
    )
