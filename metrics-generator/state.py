"""Per-service metric state used by the simulator.

Every tick the generator nudges `current` values toward `target` values,
synthesises a histogram distribution that gives the desired p99 latency,
and increments the counter-style metrics by realistic amounts based on
the current request-rate and error-rate.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# Default histogram buckets, in seconds. Covers <1ms .. >5s. The order
# matches Prometheus' "le" convention (cumulative <=).
LATENCY_BUCKETS_S: Tuple[float, ...] = (
    0.005, 0.010, 0.025, 0.050, 0.100,
    0.250, 0.500, 1.000, 2.500, 5.000,
    10.000,
)


@dataclass
class ServiceTargets:
    """The 'where we want to be' for one service in the current scenario."""

    request_rate_rps: float           # requests per second
    error_rate: float                 # 0..1 (fraction of requests that 5xx)
    latency_p99_s: float              # target p99 latency in seconds
    cpu_ratio: float                  # 0..1
    memory_bytes: float               # bytes
    health: float                     # 1 healthy, 0.5 degraded, 0 critical


@dataclass
class ServiceState:
    """Live state for one service. Counters accumulate; gauges track targets.

    The `current_*` fields move toward the active scenario's targets each
    tick using a simple exponential smoother, which avoids step-functions
    in the rate() output that the agents query.
    """

    name: str

    # Cumulative counters - only ever increase (or reset on /timeline/reset).
    requests_total_2xx: float = 0.0
    requests_total_5xx: float = 0.0
    process_cpu_seconds_total: float = 0.0

    # Histogram cumulative counts per bucket (Prometheus 'le' semantics).
    histogram_buckets: Dict[float, float] = field(default_factory=dict)
    histogram_count: float = 0.0
    histogram_sum: float = 0.0

    # Live gauge-ish values (smoothed toward target each tick).
    current_request_rate_rps: float = 0.0
    current_error_rate: float = 0.0
    current_latency_p99_s: float = 0.0
    current_cpu_ratio: float = 0.0
    current_memory_bytes: float = 0.0
    current_health: float = 1.0

    last_tick_ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.histogram_buckets:
            self.histogram_buckets = {b: 0.0 for b in LATENCY_BUCKETS_S}

    # ---------------------------------------------------------------
    # Smoothing toward targets + counter increments
    # ---------------------------------------------------------------

    def tick(self, target: ServiceTargets, alpha: float = 0.35) -> None:
        """Advance state by one push interval.

        alpha is the per-tick smoothing factor: 0 = freeze on current,
        1 = snap to target. 0.35 with a 5s push interval converges over
        ~3 ticks (~15s), which keeps rate windows readable.
        """
        now = time.time()
        dt = max(0.001, now - self.last_tick_ts)
        self.last_tick_ts = now

        self.current_request_rate_rps = _ema(
            self.current_request_rate_rps, target.request_rate_rps, alpha
        )
        self.current_error_rate = _ema(
            self.current_error_rate, target.error_rate, alpha
        )
        self.current_latency_p99_s = _ema(
            self.current_latency_p99_s, target.latency_p99_s, alpha
        )
        self.current_cpu_ratio = _ema(
            self.current_cpu_ratio, target.cpu_ratio, alpha
        )
        self.current_memory_bytes = _ema(
            self.current_memory_bytes, target.memory_bytes, alpha
        )
        self.current_health = _ema(self.current_health, target.health, alpha)

        # Increment counters based on the smoothed current request rate.
        # Add small noise so rate() values aren't suspiciously flat.
        rps = max(0.0, self.current_request_rate_rps * random.uniform(0.92, 1.08))
        n_requests = rps * dt
        n_errors = n_requests * max(0.0, self.current_error_rate)
        n_2xx = max(0.0, n_requests - n_errors)

        self.requests_total_2xx += n_2xx
        self.requests_total_5xx += n_errors

        # process_cpu_seconds_total grows at cpu_ratio * dt (a 1-core proxy).
        self.process_cpu_seconds_total += max(0.0, self.current_cpu_ratio) * dt

        # Histogram: distribute n_requests into latency buckets such that
        # the resulting p99 lands near current_latency_p99_s. We synthesise
        # a log-normal-ish distribution centered well below p99 with a long
        # tail at p99.
        latencies = _synthesize_latencies(
            n=int(n_requests),
            p99_s=max(0.001, self.current_latency_p99_s),
        )
        for lat in latencies:
            self.histogram_count += 1
            self.histogram_sum += lat
            for b in LATENCY_BUCKETS_S:
                if lat <= b:
                    self.histogram_buckets[b] += 1
            # +Inf bucket equals histogram_count.

    def reset(self) -> None:
        self.requests_total_2xx = 0.0
        self.requests_total_5xx = 0.0
        self.process_cpu_seconds_total = 0.0
        self.histogram_buckets = {b: 0.0 for b in LATENCY_BUCKETS_S}
        self.histogram_count = 0.0
        self.histogram_sum = 0.0
        self.current_request_rate_rps = 0.0
        self.current_error_rate = 0.0
        self.current_latency_p99_s = 0.0
        self.current_cpu_ratio = 0.0
        self.current_memory_bytes = 0.0
        self.current_health = 1.0
        self.last_tick_ts = time.time()

    # ---------------------------------------------------------------
    # Snapshot for dashboard / state endpoints
    # ---------------------------------------------------------------

    def snapshot(self) -> Dict:
        return {
            "service": self.name,
            "request_rate_rps": round(self.current_request_rate_rps, 2),
            "error_rate": round(self.current_error_rate, 4),
            "error_rate_pct": round(self.current_error_rate * 100, 2),
            "latency_p99_s": round(self.current_latency_p99_s, 3),
            "latency_p99_ms": round(self.current_latency_p99_s * 1000, 1),
            "cpu_ratio": round(self.current_cpu_ratio, 3),
            "cpu_pct": round(self.current_cpu_ratio * 100, 1),
            "memory_bytes": int(self.current_memory_bytes),
            "memory_mb": round(self.current_memory_bytes / (1024 * 1024), 1),
            "health": round(self.current_health, 2),
            "requests_total_2xx": int(self.requests_total_2xx),
            "requests_total_5xx": int(self.requests_total_5xx),
            "histogram_count": int(self.histogram_count),
        }


def _ema(current: float, target: float, alpha: float) -> float:
    return current + alpha * (target - current)


def _synthesize_latencies(n: int, p99_s: float) -> List[float]:
    """Generate n latencies whose 99th percentile is ~ p99_s.

    Cheap synthesis: 99% of samples are uniformly distributed over
    [p99_s * 0.05, p99_s * 0.5], the remaining 1% over [p99_s * 0.9, p99_s * 1.1].
    Good enough that histogram_quantile(0.99, rate(..._bucket)) returns
    a value close to the requested p99 once samples accumulate.
    """
    if n <= 0:
        return []
    out: List[float] = []
    tail_count = max(1, n // 100)
    body_count = max(0, n - tail_count)
    body_lo = max(0.0005, p99_s * 0.05)
    body_hi = max(body_lo * 1.01, p99_s * 0.5)
    tail_lo = max(body_hi, p99_s * 0.9)
    tail_hi = p99_s * 1.1
    for _ in range(body_count):
        out.append(random.uniform(body_lo, body_hi))
    for _ in range(tail_count):
        out.append(random.uniform(tail_lo, tail_hi))
    random.shuffle(out)
    return out


def health_label(value: float) -> str:
    """Map numeric health (0..1) back to the agents' bucket names."""
    if value >= 0.85:
        return "HEALTHY"
    if value >= 0.4:
        return "DEGRADED"
    return "CRITICAL"
