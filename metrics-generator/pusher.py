"""Build a CollectorRegistry per service and push it to a Pushgateway.

Why per-service registries: Pushgateway groups series by `grouping_key`.
Pushing each service into its own group means we can update / clear them
independently and they don't trample each other's labels.

Metric names match exactly what the PIPA agent prompts query:

    http_requests_total{service="X", status="2xx|5xx"}
    http_errors_total{service="X"}
    http_request_duration_seconds_bucket{service="X", le="..."}
    http_request_duration_seconds_count{service="X"}
    http_request_duration_seconds_sum{service="X"}
    http_request_duration_p99{service="X"}      (precomputed gauge form)
    cpu_usage_ratio{service="X"}
    process_cpu_seconds_total{service="X"}
    process_resident_memory_bytes{service="X"}
    service_health{service="X"}
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    delete_from_gateway,
    generate_latest,
    push_to_gateway,
)

from state import LATENCY_BUCKETS_S, ServiceState  # absolute; metrics-generator/ is on sys.path

log = logging.getLogger(__name__)


class Pusher:
    """Pushes simulated per-service metrics to a Prometheus Pushgateway.

    Use `dry_run=True` to skip network I/O and just log / return what
    would have been sent. Useful for local smoke testing without a
    Pushgateway running.
    """

    def __init__(
        self,
        pushgateway_url: str,
        job: str = "blast-radius-demo",
        instance: str = "sim-0",
        dry_run: bool = False,
    ):
        self.pushgateway_url = pushgateway_url.rstrip("/")
        self.job = job
        self.instance = instance
        self.dry_run = dry_run

    # ----------------------------------------------------------------
    # Per-service registry construction
    # ----------------------------------------------------------------

    def _build_registry(self, state: ServiceState) -> CollectorRegistry:
        reg = CollectorRegistry()
        labels = ["service"]
        svc = state.name

        # Counters - http_requests_total (split by status) +
        # http_errors_total (alias on the 5xx count, since the agent
        # prompt tries both forms).
        requests = Counter(
            "http_requests_total",
            "Total HTTP requests received by the service.",
            labelnames=labels + ["status"],
            registry=reg,
        )
        errors = Counter(
            "http_errors_total",
            "Total HTTP errors observed by the service (5xx).",
            labelnames=labels,
            registry=reg,
        )
        cpu_seconds = Counter(
            "process_cpu_seconds_total",
            "Cumulative CPU seconds consumed by the service process.",
            labelnames=labels,
            registry=reg,
        )

        # Counters need ._value set directly - we have cumulative totals
        # in ServiceState, not deltas.
        requests.labels(service=svc, status="2xx")._value.set(state.requests_total_2xx)
        requests.labels(service=svc, status="5xx")._value.set(state.requests_total_5xx)
        errors.labels(service=svc)._value.set(state.requests_total_5xx)
        cpu_seconds.labels(service=svc)._value.set(state.process_cpu_seconds_total)

        # Histogram - we own the bucket counts directly. prometheus_client
        # Histogram's increment path doesn't expose cumulative-bucket
        # injection, so we expose buckets via a separate Gauge family
        # named with the histogram convention. PromQL parses these as
        # histogram series identically.
        hist_bucket = Gauge(
            "http_request_duration_seconds_bucket",
            "Cumulative count of requests with duration <= le seconds.",
            labelnames=labels + ["le"],
            registry=reg,
        )
        hist_count = Gauge(
            "http_request_duration_seconds_count",
            "Total count of observed request durations.",
            labelnames=labels,
            registry=reg,
        )
        hist_sum = Gauge(
            "http_request_duration_seconds_sum",
            "Cumulative sum of observed request durations.",
            labelnames=labels,
            registry=reg,
        )

        for b in LATENCY_BUCKETS_S:
            hist_bucket.labels(service=svc, le=_le_str(b)).set(
                state.histogram_buckets.get(b, 0.0)
            )
        # +Inf bucket = total observation count
        hist_bucket.labels(service=svc, le="+Inf").set(state.histogram_count)
        hist_count.labels(service=svc).set(state.histogram_count)
        hist_sum.labels(service=svc).set(state.histogram_sum)

        # Precomputed p99 gauge - alternate query in the agent prompt.
        p99 = Gauge(
            "http_request_duration_p99",
            "Precomputed p99 request duration in seconds.",
            labelnames=labels,
            registry=reg,
        )
        p99.labels(service=svc).set(state.current_latency_p99_s)

        # Other gauges.
        cpu = Gauge(
            "cpu_usage_ratio",
            "CPU utilisation as a 0..1 ratio.",
            labelnames=labels,
            registry=reg,
        )
        cpu.labels(service=svc).set(state.current_cpu_ratio)

        mem = Gauge(
            "process_resident_memory_bytes",
            "Resident memory in bytes.",
            labelnames=labels,
            registry=reg,
        )
        mem.labels(service=svc).set(state.current_memory_bytes)

        health = Gauge(
            "service_health",
            "Service health: 1 healthy, 0.5 degraded, 0 critical.",
            labelnames=labels,
            registry=reg,
        )
        health.labels(service=svc).set(state.current_health)

        return reg

    # ----------------------------------------------------------------
    # Network ops
    # ----------------------------------------------------------------

    def push_service(self, state: ServiceState) -> Optional[bytes]:
        """Push one service's registry. Returns the exposition text in
        dry-run mode for smoke testing, otherwise returns None."""
        reg = self._build_registry(state)

        if self.dry_run:
            text = generate_latest(reg)
            log.info(
                "[dry-run] would push %d bytes for service=%s",
                len(text),
                state.name,
            )
            return text

        push_to_gateway(
            self.pushgateway_url,
            job=self.job,
            registry=reg,
            grouping_key={"service": state.name, "instance": self.instance},
        )
        return None

    def push_all(self, states: Iterable[ServiceState]) -> Dict[str, str]:
        """Push every service. Returns a per-service status string. We
        catch per-service exceptions so one bad service doesn't kill the
        whole tick."""
        results: Dict[str, str] = {}
        for state in states:
            try:
                self.push_service(state)
                results[state.name] = "ok"
            except Exception as exc:  # noqa: BLE001
                log.warning("push failed for %s: %s", state.name, exc)
                results[state.name] = f"error: {exc}"
        return results

    def delete_all(self, service_names: Iterable[str]) -> Dict[str, str]:
        """Wipe every service's group out of the Pushgateway. Used by
        /timeline/reset so old samples don't linger."""
        results: Dict[str, str] = {}
        for name in service_names:
            if self.dry_run:
                results[name] = "dry-run"
                continue
            try:
                delete_from_gateway(
                    self.pushgateway_url,
                    job=self.job,
                    grouping_key={"service": name, "instance": self.instance},
                )
                results[name] = "deleted"
            except Exception as exc:  # noqa: BLE001
                log.warning("delete failed for %s: %s", name, exc)
                results[name] = f"error: {exc}"
        return results


def _le_str(b: float) -> str:
    """Match Prometheus' canonical 'le' label formatting (no scientific)."""
    if b == int(b):
        return f"{int(b)}.0"
    return f"{b}".rstrip("0").rstrip(".") if "." in f"{b}" else f"{b}"
