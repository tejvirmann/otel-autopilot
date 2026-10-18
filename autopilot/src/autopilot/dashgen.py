"""Dashboards as code.

standard: a templated RED/SLO dashboard whose panels are Grafana *library panels*, shared by every
          service (pick one with the $service variable). Fix a panel once, every dashboard updates.
oneoff:   a tailored dashboard for one service, built from what Prometheus says that service emits.
Queries target OTel Collector span metrics (traces_span_metrics_*) and the GenAI token histogram.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

DS = {"type": "prometheus", "uid": "prometheus"}
CALLS = "traces_span_metrics_calls_total"
DUR = "traces_span_metrics_duration_milliseconds_bucket"
SVC = 'service_name=~"$service"'
SERVER = 'span_kind="SPAN_KIND_SERVER"'


def _target(expr, legend="", ref="A"):
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}


def _panel(title, expr, legend="", unit="short", kind="timeseries", desc=""):
    return {"type": kind, "title": title, "description": desc, "datasource": DS,
            "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            "targets": [_target(expr, legend)]}


def standard_panels(selector=SVC) -> dict[str, dict]:
    """name -> panel model. Keys become library-panel names/uids."""
    s = selector
    return {
        "request-rate": _panel("Request rate (req/s)", f'sum by (http_route) (rate({CALLS}{{{s},{SERVER}}}[1m]))',
                               "{{http_route}}", "reqps", desc="RED: Rate. Server spans per route."),
        "error-rate": _panel("Error rate (%)",
                             f'100 * sum(rate({CALLS}{{{s},status_code="STATUS_CODE_ERROR",span_kind!="SPAN_KIND_INTERNAL"}}[1m])) '
                             f'/ clamp_min(sum(rate({CALLS}{{{s},{SERVER}}}[1m])), 0.001)', "errors", "percent",
                             desc="RED: Errors. Failed spans vs total requests."),
        "latency-p95": _panel("Latency p95 by route", f'histogram_quantile(0.95, sum by (le, http_route) (rate({DUR}{{{s},{SERVER}}}[1m])))',
                              "{{http_route}}", "ms", desc="RED: Duration."),
        "latency-p50": _panel("Latency p50 by route", f'histogram_quantile(0.50, sum by (le, http_route) (rate({DUR}{{{s},{SERVER}}}[1m])))',
                              "{{http_route}}", "ms"),
        "db-calls": _panel("DB spans per request", f'sum(rate({CALLS}{{{s},db_system!=""}}[1m])) / clamp_min(sum(rate({CALLS}{{{s},{SERVER}}}[1m])), 0.001)',
                           "db calls / request", "short", desc="High values signal N+1 queries."),
        "errors-by-op": _panel("Errors by operation", f'sum by (span_name) (rate({CALLS}{{{s},status_code="STATUS_CODE_ERROR"}}[1m]))',
                               "{{span_name}}", "ops"),
        "genai-tokens": _panel("GenAI tokens/s", f'sum by (gen_ai_token_type, gen_ai_request_model) (rate(gen_ai_client_token_usage_sum{{exported_job=~"$service"}}[1m]))',
                               "{{gen_ai_request_model}} {{gen_ai_token_type}}", "short", desc="OTel GenAI semantic conventions."),
    }


def _slo_stat():
    p = _panel("Availability (SLO 99.5%)", f'100 - (100 * sum(rate({CALLS}{{{SVC},status_code="STATUS_CODE_ERROR",span_kind!="SPAN_KIND_INTERNAL"}}[5m])) '
               f'/ clamp_min(sum(rate({CALLS}{{{SVC},{SERVER}}}[5m])), 0.001))', "", "percent", "stat")
    p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": [
        {"color": "red", "value": None}, {"color": "orange", "value": 99}, {"color": "green", "value": 99.5}]}
    return p


def _service_var():
    return {"name": "service", "type": "query", "datasource": DS, "label": "Service",
            "query": {"query": f"label_values({CALLS}, service_name)", "refId": "q"},
            "refresh": 2, "includeAll": False, "current": {}}


def _dash(uid, title, panels, variables, tags):
    return {"uid": uid, "title": title, "tags": ["otel-autopilot", *tags], "schemaVersion": 39, "version": 1,
            "time": {"from": "now-15m", "to": "now"}, "refresh": "10s", "editable": True,
            "templating": {"list": variables}, "panels": panels}


def _grid(panels, cols=2, h=8):
    out = []
    for i, p in enumerate(panels):
        p = dict(p)
        p["id"] = i + 1
        p["gridPos"] = {"x": (i % cols) * (24 // cols), "y": (i // cols) * h, "w": 24 // cols, "h": h}
        out.append(p)
    return out


def build_standard():
    libs = {k: v for k, v in standard_panels().items()}
    lib_elements = [{"uid": f"otel-{k}", "name": f"OTel / {v['title']}", "kind": 1, "model": v} for k, v in libs.items()]
    refs = [{"libraryPanel": {"uid": e["uid"], "name": e["name"]}, "title": e["model"]["title"]} for e in lib_elements]
    slo = _slo_stat()
    panels = _grid(refs)
    for p in panels:
        p["gridPos"]["y"] += 4
    slo["id"], slo["gridPos"] = len(panels) + 1, {"x": 0, "y": 0, "w": 24, "h": 4}
    panels.insert(0, slo)
    return lib_elements, _dash("otel-standard-red", "Service Overview (standard)", panels, [_service_var()], ["standard"])


def discover(service: str, prom: str = "http://localhost:9090") -> dict:
    def q(expr):
        r = httpx.get(f"{prom}/api/v1/query", params={"query": expr}, timeout=10).json()
        return r["data"]["result"]
    routes = sorted({r["metric"]["http_route"] for r in q(f'{CALLS}{{service_name="{service}",{SERVER}}}') if r["metric"].get("http_route")})
    return {"routes": routes,
            "db": bool(q(f'{CALLS}{{service_name="{service}",db_system!=""}}')),
            "genai": bool(q(f'gen_ai_client_token_usage_count{{exported_job="{service}"}}'))}


def build_oneoff(service: str, routes: list[str], db: bool, genai: bool):
    sel = f'service_name="{service}"'
    panels = [_panel("Request rate (req/s)", f'sum by (http_route) (rate({CALLS}{{{sel},{SERVER}}}[1m]))', "{{http_route}}", "reqps"),
              _panel("Errors by operation", f'sum by (span_name) (rate({CALLS}{{{sel},status_code="STATUS_CODE_ERROR"}}[1m]))', "{{span_name}}", "ops")]
    for r in routes:
        if r in ("/openapi.json", "/docs", "/redoc"):
            continue
        panels.append(_panel(f"{r}: p50 / p95 latency",
                             f'histogram_quantile(0.5, sum by (le) (rate({DUR}{{{sel},{SERVER},http_route="{r}"}}[1m])))', "p50", "ms"))
        panels[-1]["targets"].append(_target(f'histogram_quantile(0.95, sum by (le) (rate({DUR}{{{sel},{SERVER},http_route="{r}"}}[1m])))', "p95", "B"))
    if db:
        panels.append(_panel("DB spans per request (N+1 detector)", f'sum(rate({CALLS}{{{sel},db_system!=""}}[1m])) / clamp_min(sum(rate({CALLS}{{{sel},{SERVER}}}[1m])), 0.001)', "db calls / request"))
    if genai:
        panels.append(_panel("GenAI tokens/s", f'sum by (gen_ai_token_type) (rate(gen_ai_client_token_usage_sum{{exported_job="{service}"}}[1m]))', "{{gen_ai_token_type}}"))
    return _dash(f"otel-oneoff-{service}", f"{service} (generated)", _grid(panels), [], ["oneoff", service])


def push(out: Path, grafana: str, auth: str):
    user, pw = auth.split(":", 1)
    c = httpx.Client(base_url=grafana, auth=(user, pw), timeout=15)
    for f in sorted((out / "library-panels").glob("*.json")):
        el = json.loads(f.read_text())
        cur = c.get(f"/api/library-elements/{el['uid']}")
        if cur.status_code == 200:  # update in place: panels shared by dashboards can't be deleted
            r = c.patch(f"/api/library-elements/{el['uid']}", json={**el, "version": cur.json()["result"]["version"]})
        else:
            r = c.post("/api/library-elements", json=el)
        r.raise_for_status()
    for f in sorted(out.glob("*.json")):
        r = c.post("/api/dashboards/db", json={"dashboard": json.loads(f.read_text()), "overwrite": True})
        r.raise_for_status()
        print("pushed", f.name, "->", grafana + r.json().get("url", ""))


def cli(a):
    out = Path(a.out)
    if a.what == "push":
        return push(out, a.grafana, a.auth)
    (out / "library-panels").mkdir(parents=True, exist_ok=True)
    if a.what == "standard":
        libs, dash = build_standard()
        for el in libs:
            (out / "library-panels" / f"{el['uid']}.json").write_text(json.dumps(el, indent=2))
        (out / "service-overview.json").write_text(json.dumps(dash, indent=2))
        print(f"wrote {len(libs)} library panels + service-overview.json to {out}")
    else:
        d = discover(a.service)
        dash = build_oneoff(a.service, d["routes"], d["db"], d["genai"])
        (out / f"{a.service}.json").write_text(json.dumps(dash, indent=2))
        print(f"discovered routes={d['routes']} db={d['db']} genai={d['genai']}; wrote {a.service}.json")
