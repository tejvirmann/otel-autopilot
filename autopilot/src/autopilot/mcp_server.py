"""MCP server: lets any coding agent verify instrumentation and confirm data landed in the backend.

Code edits stay with the agent's own file tools; this server covers the *live/stateful* parts.
Pair with Grafana's official mcp-grafana for dashboard management.
"""
from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

from . import dashgen
from .report import render
from .runner import verify

mcp = FastMCP("otel-autopilot")
PROM = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
TEMPO = os.getenv("TEMPO_URL", "http://localhost:3200")


@mcp.tool()
def verify_instrumentation(app_dir: str, traffic_file: str | None = None) -> str:
    """Run the app in app_dir (needs app.py exposing `app`, and payments_stub if used) with synthetic traffic
    against a local collector and score the telemetry 0-100. Returns a per-check report with fix hints.
    Call after every instrumentation change; aim for 100 before opening a PR."""
    return render(verify(app_dir, traffic_file), color=False)


@mcp.tool()
def query_prometheus(promql: str) -> str:
    """Instant PromQL query against the backend; use to confirm metrics (e.g. span metrics) landed."""
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": promql}, timeout=15).json()
    rows = [f"{x['metric']} => {x['value'][1]}" for x in r.get("data", {}).get("result", [])[:25]]
    return "\n".join(rows) or "no series"


@mcp.tool()
def search_traces(service: str, min_duration_ms: int = 0, limit: int = 5) -> str:
    """Find recent traces for a service in Tempo (optionally with a span slower than min_duration_ms)."""
    q = f'{{ resource.service.name = "{service}" && duration > {min_duration_ms}ms }}'
    r = httpx.get(f"{TEMPO}/api/search", params={"q": q, "limit": limit}, timeout=15).json()
    rows = []
    for t in r.get("traces", []):
        spans = t.get("spanSet", {}).get("spans", [])
        ms = max((int(x["durationNanos"]) for x in spans), default=0) / 1e6
        rows.append(f"{t['traceID']} root={t.get('rootTraceName')} matching_span={ms:.0f}ms")
    return "\n".join(rows) or "no traces"


@mcp.tool()
def generate_dashboards(kind: str, service: str = "", out_dir: str = "dashboards/out") -> str:
    """Write Grafana dashboards-as-code JSON. kind='standard' (shared library panels + $service variable)
    or kind='oneoff' (tailored to what `service` emits). Push with `autopilot dash push` or mcp-grafana."""
    import argparse
    dashgen.cli(argparse.Namespace(what=kind, service=service, out=out_dir))
    return f"generated {kind} dashboards in {out_dir}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
