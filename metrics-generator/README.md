# PIPA metrics generator

A scenario-driven Prometheus metrics simulator for the PIPA worker
agents in [`agents-PIPA/`](../). Pushes the exact PromQL series the
agents query to a Pushgateway, scripted as a rolling-deployment +
blast-radius timeline so the agents can reason about a simulated bad
deploy without anything actually deploying.

## What it produces

For each service in `{checkout_svc, inventory, payment, notification}`:

```
http_requests_total{service="X", status="2xx|5xx"}                 (counter)
http_errors_total{service="X"}                                     (counter, alias of 5xx)
http_request_duration_seconds_bucket{service="X", le="..."}        (histogram, lets histogram_quantile work)
http_request_duration_seconds_count{service="X"}
http_request_duration_seconds_sum{service="X"}
http_request_duration_p99{service="X"}                             (precomputed gauge, alt query)
cpu_usage_ratio{service="X"}                                       (gauge, 0..1)
process_cpu_seconds_total{service="X"}                             (counter)
process_resident_memory_bytes{service="X"}                         (gauge)
service_health{service="X"}                                        (gauge, 1 healthy, 0.5 degraded, 0 critical)
```

Each service is its own Pushgateway group
(`grouping_key={"service": "<svc>", "instance": "sim-0"}`) under job
`blast-radius-demo`, so they can be updated and cleared independently.

## Architecture

```
You (dashboard)  -->  FastAPI :8090  -->  Pushgateway :9091  -->  Prometheus :9090
                                                                       ^
                                                                       |
                                              PIPA agents (Harness Worker Agents) query here
```

## Run locally

```bash
# from the repo root
./scripts/start_metrics_generator.sh
# open http://localhost:8090/
```

The script reuses `.venv/` if you already have one (e.g. from running
the local checkout demo), otherwise falls back to system `python3`.

Override env vars to point at a different Pushgateway:

```bash
PUSHGATEWAY_URL=http://1.2.3.4:9091 \
PUSH_INTERVAL_SECONDS=3 \
./scripts/start_metrics_generator.sh

# or to develop without a Pushgateway running:
DRY_RUN=1 ./scripts/start_metrics_generator.sh
```

## Run in Docker

```bash
docker build -f metrics-generator/Dockerfile \
  -t pritishharness/blast-radius-metrics-gen:1.0.0 metrics-generator/
docker run --rm -p 8090:8090 \
  -e PUSHGATEWAY_URL=http://8.229.139.162:9091 \
  pritishharness/blast-radius-metrics-gen:1.0.0
```

## Scenarios

Six named phases in [`scenarios.py`](scenarios.py):

| Scenario             | What the agents will see                                        |
|----------------------|-----------------------------------------------------------------|
| `steady`             | All services healthy (err 0.1%, p99 ~120ms, cpu 30%)            |
| `deploy_starting`    | checkout warm-up, slight latency bump, downstreams unchanged    |
| `bad_deploy_rolling` | checkout err climbs to ~18%, p99 600ms, cpu 75%; small downstream uptick |
| `cascade_active`     | checkout CRITICAL (28%, 1.4s, cpu 88%); payment/inventory DEGRADED |
| `recovering`         | checkout near baseline; downstreams stay elevated for ~30s more |
| `recovered`          | All services back to baseline                                   |

Auto-timeline (`POST /timeline/start`):

```
steady (10s) -> deploy_starting (30s) -> bad_deploy_rolling (60s)
              -> cascade_active (90s) -> recovering (60s) -> recovered (30s)
total: ~4m 40s
```

## REST API

```
GET  /health              liveness + current scenario + tick count
GET  /state               full snapshot (live values, scenario, timeline progress)
GET  /scenarios           list scenarios + auto-timeline schedule
POST /scenario/{name}     switch scenario immediately (steady, bad_deploy_rolling, ...)
POST /timeline/start      start the auto blast-radius timeline
POST /timeline/stop       freeze on whatever scenario is current
POST /timeline/reset      wipe Pushgateway groups, return to steady, zero counters
GET  /preview             per-service Prometheus exposition text (debug)
```

## Smoke-testing the agents against this

1. Start the generator with `./scripts/start_metrics_generator.sh`.
2. Click **Start blast-radius timeline** in the dashboard (or
   `curl -X POST http://localhost:8090/timeline/start`).
3. Wait ~30s (so Prometheus has 2+ samples and `rate()` returns data).
4. Sanity-check Prometheus directly:

   ```
   curl -G http://8.229.139.162:9090/api/v1/query \
     --data-urlencode 'query=rate(http_errors_total{service="checkout_svc"}[1m])'
   ```

5. Trigger your PIPA pipeline. Agent 1's risk score should climb from
   ~1 in `steady` to ~8 in `cascade_active`, and Agent 3 should land on
   `BLOCK`.

## Hand-off to the PIPA agents

Use these pipeline variables when triggering the PIPA pipeline against
the simulator:

```
targetService          = checkout_svc
environment            = sim
prometheusUrl          = http://8.229.139.162:9090
knownDependencies      = inventory,payment,notification
deploymentPipelineId   = <whatever>
deploymentExecutionId  = <whatever>
```

The metric-name + label combination matches the PromQL queries the
agent prompts try (in order); the first one that returns data wins.

## What's intentionally not here

- No alerting rules. Agents do their own thresholding.
- No persistence. Restart resets to `steady` and zeros counters
  (Pushgateway groups linger until you call `/timeline/reset`).
- No metric-name aliasing for the `-service` suffix variants
  (`checkout-service`, etc.) - the simulator emits the names that match
  this repo's checkout_svc Harness identifier. If you want to add them
  later, edit `ALL_SERVICES` in [`scenarios.py`](scenarios.py).
