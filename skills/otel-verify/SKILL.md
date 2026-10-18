---
name: otel-verify
description: Verify that OpenTelemetry telemetry is correct by running the service with synthetic traffic and scoring what reaches a collector. Use after any instrumentation change, in CI, or when asked whether tracing "actually works".
---

# Verify telemetry

Do not claim instrumentation works because the code looks right. Run it.

- Tool: MCP `verify_instrumentation(app_dir, traffic_file?)`, or CLI `uv run autopilot verify <app_dir> [--min-score 90] [--json]`.
- The verifier starts the app, drives `traffic.json`, collects spans over OTLP and checks: spans arrive; `service.name`/version/env; a SERVER span with `http.route` for every endpoint; route-template span names (no raw IDs); DB spans; outbound HTTP spans linked to the request trace; failures recorded as ERROR + exception event; no PII/secrets in attributes; GenAI attributes and token usage on LLM calls.
- Report the score and each failing check verbatim, with its fix hint.
- To confirm data reached a real backend, use MCP `query_prometheus` (e.g. `sum(traces_span_metrics_calls_total{service_name="X"})`) and `search_traces`.
- CI gate: `--min-score N` exits non-zero below N. Add a `traffic.json` entry with `"expect_error_span": true` for any request that should fail.
