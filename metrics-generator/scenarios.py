"""Scenario library for the PIPA metrics simulator.

Each scenario is a per-service `ServiceTargets` snapshot that the
generator's tick loop smooths the live state toward.

The auto-timeline strings these scenarios together so the agents see a
plausible, evolving signal: steady -> deploy starting -> bad deploy
rolling out -> full blast radius -> recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from state import ServiceTargets  # absolute import; metrics-generator/ is on sys.path


# ---------------------------------------------------------------------------
# Service identities. checkout_svc is the upstream / target of the deploy;
# the rest are downstream and own their own blast-radius signals.
# ---------------------------------------------------------------------------

CHECKOUT = "checkout_svc"
INVENTORY = "inventory"
PAYMENT = "payment"
NOTIFICATION = "notification"

ALL_SERVICES: List[str] = [CHECKOUT, INVENTORY, PAYMENT, NOTIFICATION]


# Memory baselines (bytes) - small enough to be plausible but distinct so
# the dashboard shows variety.
_MEM = {
    CHECKOUT: 180 * 1024 * 1024,
    INVENTORY: 120 * 1024 * 1024,
    PAYMENT: 140 * 1024 * 1024,
    NOTIFICATION: 90 * 1024 * 1024,
}


def _baseline(service: str, *, rps: float = 0.0) -> ServiceTargets:
    """Healthy baseline for any service. RPS is overridable per service."""
    return ServiceTargets(
        request_rate_rps=rps,
        error_rate=0.001,                    # 0.1%
        latency_p99_s=0.120,                 # 120ms
        cpu_ratio=0.30,                      # 30%
        memory_bytes=_MEM[service],
        health=1.0,
    )


def _checkout(rps, err, p99, cpu, mem_mult, health):
    return ServiceTargets(
        request_rate_rps=rps,
        error_rate=err,
        latency_p99_s=p99,
        cpu_ratio=cpu,
        memory_bytes=_MEM[CHECKOUT] * mem_mult,
        health=health,
    )


def _down(name, rps, err, p99, cpu, mem_mult, health):
    return ServiceTargets(
        request_rate_rps=rps,
        error_rate=err,
        latency_p99_s=p99,
        cpu_ratio=cpu,
        memory_bytes=_MEM[name] * mem_mult,
        health=health,
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


SCENARIOS: Dict[str, Dict[str, ServiceTargets]] = {
    # All services healthy. Default starting state.
    "steady": {
        CHECKOUT:     _baseline(CHECKOUT,     rps=80),
        INVENTORY:    _baseline(INVENTORY,    rps=80),
        PAYMENT:      _baseline(PAYMENT,      rps=80),
        NOTIFICATION: _baseline(NOTIFICATION, rps=80),
    },

    # Brief warm-up phase - new pods accepting traffic. p99 nudges up,
    # error rate stays at baseline, downstreams unchanged.
    "deploy_starting": {
        CHECKOUT:     _checkout(rps=70, err=0.005, p99=0.180, cpu=0.45,
                                mem_mult=1.05, health=1.0),
        INVENTORY:    _baseline(INVENTORY,    rps=70),
        PAYMENT:      _baseline(PAYMENT,      rps=70),
        NOTIFICATION: _baseline(NOTIFICATION, rps=70),
    },

    # Broken pods take traffic. checkout error rate climbs, latency
    # climbs, cpu rises. Downstreams see early signs of upstream pressure
    # but aren't yet broken themselves.
    "bad_deploy_rolling": {
        CHECKOUT:     _checkout(rps=85, err=0.18, p99=0.600, cpu=0.75,
                                mem_mult=1.15, health=0.55),
        INVENTORY:    _down(INVENTORY,    rps=85, err=0.02, p99=0.200,
                            cpu=0.45, mem_mult=1.05, health=0.85),
        PAYMENT:      _down(PAYMENT,      rps=82, err=0.025, p99=0.250,
                            cpu=0.50, mem_mult=1.05, health=0.85),
        NOTIFICATION: _down(NOTIFICATION, rps=70, err=0.005, p99=0.130,
                            cpu=0.32, mem_mult=1.0, health=1.0),
    },

    # Full blast radius. checkout broken, inventory holding stuck
    # reservations, payment ledger orphaned, notification queue backed up.
    "cascade_active": {
        CHECKOUT:     _checkout(rps=92, err=0.28, p99=1.4, cpu=0.88,
                                mem_mult=1.30, health=0.0),
        INVENTORY:    _down(INVENTORY,    rps=92, err=0.12, p99=0.890,
                            cpu=0.70, mem_mult=1.20, health=0.4),
        PAYMENT:      _down(PAYMENT,      rps=90, err=0.18, p99=1.1,
                            cpu=0.75, mem_mult=1.20, health=0.3),
        NOTIFICATION: _down(NOTIFICATION, rps=60, err=0.05, p99=0.600,
                            cpu=0.55, mem_mult=1.10, health=0.7),
    },

    # Rolling back. checkout returns to baseline, but the downstreams
    # remain elevated for the rest of this phase - the "stuck state
    # outlasts the bad deploy" detail of the blast-radius story.
    "recovering": {
        CHECKOUT:     _checkout(rps=80, err=0.01, p99=0.250, cpu=0.40,
                                mem_mult=1.05, health=0.85),
        INVENTORY:    _down(INVENTORY,    rps=80, err=0.06, p99=0.500,
                            cpu=0.55, mem_mult=1.10, health=0.6),
        PAYMENT:      _down(PAYMENT,      rps=80, err=0.08, p99=0.650,
                            cpu=0.60, mem_mult=1.10, health=0.5),
        NOTIFICATION: _down(NOTIFICATION, rps=70, err=0.02, p99=0.300,
                            cpu=0.40, mem_mult=1.0, health=0.85),
    },

    # All services back to baseline. Demo end state.
    "recovered": {
        CHECKOUT:     _baseline(CHECKOUT,     rps=80),
        INVENTORY:    _baseline(INVENTORY,    rps=80),
        PAYMENT:      _baseline(PAYMENT,      rps=80),
        NOTIFICATION: _baseline(NOTIFICATION, rps=80),
    },
}


SCENARIO_DESCRIPTIONS: Dict[str, str] = {
    "steady":             "All four services healthy. Default starting state.",
    "deploy_starting":    "checkout_svc warm-up: brief latency bump, no errors.",
    "bad_deploy_rolling": "Broken checkout pods take traffic. Error rate ramps to ~18%, downstreams see early pressure.",
    "cascade_active":     "Full blast radius. checkout CRITICAL, inventory + payment DEGRADED, notification queue backed up.",
    "recovering":         "Rollback in progress. checkout near baseline, downstreams still elevated.",
    "recovered":          "Back to baseline. Demo end state.",
}


# ---------------------------------------------------------------------------
# Auto timeline - chains scenarios with dwell durations (seconds)
# ---------------------------------------------------------------------------


@dataclass
class TimelinePhase:
    scenario: str
    dwell_seconds: int


AUTO_TIMELINE: List[TimelinePhase] = [
    TimelinePhase("steady",             10),
    TimelinePhase("deploy_starting",    30),
    TimelinePhase("bad_deploy_rolling", 60),
    TimelinePhase("cascade_active",     90),
    TimelinePhase("recovering",         60),
    TimelinePhase("recovered",          30),  # 30s of clean state, then it stays here
]


def total_timeline_seconds() -> int:
    return sum(p.dwell_seconds for p in AUTO_TIMELINE)
