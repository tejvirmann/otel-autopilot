---
name: otel-instrument
description: Add vendor-neutral OpenTelemetry instrumentation to a Python/FastAPI service using the otel-kit distro, then prove it with the verifier. Use when asked to instrument, add tracing/metrics/observability, or raise an instrumentation score.
---

# Instrument a Python service with otel-kit

Goal: a reviewable PR whose telemetry is *verified*, not assumed. Never auto-merge. Stay vendor-neutral: export OTLP only, configure endpoints via standard `OTEL_*` env vars.

## Procedure
1. **Discover** (read-only). Find the app entry point, routes, DB drivers, outbound HTTP clients, LLM calls, and every place exceptions are caught and swallowed. List them in `instrumentation-plan.md` under "Findings".
2. **Baseline.** Run the `verify_instrumentation` MCP tool (or `uv run autopilot verify <app_dir>`). Record the score in the plan.
3. **Instrument** with the minimum change:
   - `import otelkit` and call `otelkit.init("<service-name>", app=app, version="...")` right after creating the FastAPI app. This sets resource attributes, OTLP export, PII scrubbing, and enables FastAPI, httpx and sqlite3 instrumentation.
   - Wrap meaningful business operations in `with otelkit.business_span("checkout.charge", **attrs):`. Span names must be low-cardinality (no IDs). Put IDs in attributes only if not PII.
   - Wrap every LLM call in `with otelkit.genai_call(system, model) as call:` and call `call.record(input_tokens, output_tokens)`.
   - **Do not swallow errors silently.** Where an exception is caught and handled, call `span.record_exception(e)` and `span.set_status(Status(StatusCode.ERROR, "..."))` first.
   - Do NOT wrap or re-export the OpenTelemetry API; use `opentelemetry.trace` directly for anything custom.
4. **Verify** again. Fix every FAIL using the report's fix hints. Repeat until 100 or until a hint requires a judgment call (then stop and ask a human).
5. **Write `instrumentation-plan.md`**: what changed and why, before/after score, anything intentionally skipped, and risks (e.g. new dependency, attribute cardinality).

## Environment
`otelkit` and the verifier are installed in the repo's uv environment, not the system Python. If the task prompt gives a project path, run Python and the CLI as `uv run --project <path> ...`. Don't search the filesystem for them.

## Known gotchas
- `sqlite3` instrumentation traces **cursor** calls only. `connection.execute(...)` shortcuts produce no DB spans: use `connection.cursor().execute(...)`. (Other drivers differ; check the verifier.)
- Raw string-built SQL puts user data (emails) into `db.statement`. otel-kit scrubs it on export, but flag the SQL-injection risk to the human in the plan; do not silently rewrite queries.
- Do not remove or "fix" N+1 queries in this task. Surface them in the plan; they are a follow-on change measured against the new baseline.

## Stop and ask a human when
- A change would alter business logic or return values beyond error recording.
- The service is not Python/FastAPI, or has multiple services that need cross-service propagation decisions.
- The verifier fails for a reason the hint does not explain.
