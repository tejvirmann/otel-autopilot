---
name: otel-dashboards
description: Generate Grafana dashboards as code from verified telemetry, either the shared standard service dashboard built on library panels or a one-off dashboard tailored to one service. Use after instrumentation is verified, or when asked for dashboards/SLOs/RED metrics.
---

# Dashboards as code

Prerequisite: telemetry verified (see `otel-verify`) and flowing through a collector that runs the `spanmetrics` connector (see `stack/otel-collector.yaml`).

- **Standard (default for any service):** `uv run autopilot dash standard --out dashboards/out` writes 7 shared *library panels* (rate, errors, p50/p95, DB-calls-per-request, errors by operation, GenAI tokens) and a `service-overview` dashboard with a `$service` variable. Every service gets the same dashboard; fixing a library panel updates all dashboards that use it.
- **One-off:** `uv run autopilot dash oneoff --service <name>` discovers routes, DB and GenAI usage from Prometheus and writes a tailored dashboard (per-route latency, N+1 detector).
- **Apply:** `uv run autopilot dash push --out <dir>` (idempotent; updates library panels in place), or use the official Grafana MCP server (`mcp-grafana`) tools.
- Commit the generated JSON; never hand-edit it in the Grafana UI without exporting back.
- After pushing, query the panel expressions via `query_prometheus` and confirm none are empty before reporting done.
