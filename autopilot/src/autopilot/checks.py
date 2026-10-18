"""Verification checks over collected spans. Each returns (passed, detail, fix_hint)."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

SERVER, CLIENT = 2, 3
ERROR = 2
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
SENSITIVE_KEY = re.compile(r"(authorization|cookie|password|secret|api[-_.]?key)", re.I)
SPAN_NAME_BUDGET = 40


@dataclass
class Result:
    id: str
    title: str
    weight: int
    passed: bool
    detail: str
    fix: str

    def to_dict(self):
        return asdict(self)


def run_checks(spans: list[dict], traffic: dict) -> list[Result]:
    out: list[Result] = []

    def add(id, title, weight, ok, detail, fix):
        out.append(Result(id, title, weight, bool(ok), detail, "" if ok else fix))

    if not spans:
        add("spans-received", "Any spans reach the collector", 100, False,
            "0 spans received while traffic was driven.",
            "Call otelkit.init(service_name, app=app) at startup and ensure OTEL_EXPORTER_OTLP_ENDPOINT is honored.")
        return out
    add("spans-received", "Any spans reach the collector", 5, True, f"{len(spans)} spans received.", "")

    res = spans[0]["resource"]
    svc = res.get("service.name", "")
    ok = bool(svc) and not svc.startswith("unknown_service")
    add("res-service-name", "service.name is set", 10, ok, f"service.name={svc!r}",
        "Pass a real service name to init().")
    missing = [k for k in ("service.version", "deployment.environment") if k not in res]
    add("res-version-env", "service.version and deployment.environment set", 5, not missing,
        f"missing: {missing}" if missing else "present", "Set version/env in init() or SERVICE_VERSION/DEPLOY_ENV.")

    servers = [s for s in spans if s["kind"] == SERVER]
    routes = {s["attrs"].get("http.route") for s in servers}
    expected = {r["path"].split("?")[0] for r in traffic["requests"]}
    def covered(path):
        return any(r and re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", r), path) for r in routes)
    uncovered = sorted(p for p in expected if not covered(p))
    add("server-spans", "Server span with http.route for every driven endpoint", 15, not uncovered,
        f"uncovered: {uncovered}" if uncovered else f"routes: {sorted(r for r in routes if r)}",
        "Instrument the FastAPI app (otelkit.init(..., app=app)) so every route gets a SERVER span with http.route.")

    names = {s["name"] for s in spans}
    raw_id_names = [n for n in names if re.search(r"/\d{2,}", n)]
    add("low-cardinality-names", "Span names use route templates, not raw IDs", 10,
        not raw_id_names and len(names) <= SPAN_NAME_BUDGET,
        f"{len(names)} distinct span names; raw-ID names: {raw_id_names[:3]}",
        "Use http.route templates (/orders/{order_id}) for span names; never put IDs in names.")

    add("db-spans", "Database calls are traced", 10, any("db.system" in s["attrs"] for s in spans),
        f"{sum('db.system' in s['attrs'] for s in spans)} DB spans", "Enable DB instrumentation for the driver. For sqlite3, connection.execute() shortcuts are NOT traced: use connection.cursor().execute().")

    clients = [s for s in spans if s["kind"] == CLIENT and ("http.method" in s["attrs"] or "http.request.method" in s["attrs"])]
    by_id = {s["span_id"]: s for s in spans}
    linked = [c for c in clients if c["parent_id"] in by_id and by_id[c["parent_id"]]["trace_id"] == c["trace_id"]]
    add("outbound-http", "Outbound HTTP calls traced, linked to the request trace", 10,
        bool(clients) and len(linked) == len(clients), f"{len(clients)} client spans, {len(linked)} linked to a parent",
        "Enable HTTP client instrumentation so outbound calls propagate traceparent.")

    expect_err = any(r.get("expect_error_span") for r in traffic["requests"])
    err_spans = [s for s in spans if s["status"] == ERROR and any(e["name"] == "exception" for e in s["events"])]
    add("errors-recorded", "Failures are recorded on spans (status=ERROR + exception event)", 15,
        (not expect_err) or bool(err_spans), f"{len(err_spans)} spans with recorded exceptions",
        "Do not swallow exceptions: span.record_exception(e) and span.set_status(ERROR) before handling.")

    leaks = []
    for s in spans:
        for k, v in s["attrs"].items():
            if SENSITIVE_KEY.search(k) and v != "[REDACTED]":
                leaks.append(f"{k} on {s['name']}")
            elif isinstance(v, str) and (EMAIL.search(v) or CARD.search(v)):
                leaks.append(f"{k}={v[:60]!r} on {s['name']}")
    add("no-pii", "No PII or secrets in span attributes", 10, not leaks,
        "clean" if not leaks else f"{len(leaks)} leak(s), e.g. {leaks[0]}",
        "Use otelkit.init() (scrubs emails/cards/secrets) and avoid putting user data in attributes.")

    gen = [s for s in spans if "gen_ai.system" in s["attrs"]]
    ok = bool(gen) and all("gen_ai.usage.input_tokens" in s["attrs"] for s in gen)
    add("genai", "LLM calls carry GenAI semantic-convention attributes and token usage", 10, ok,
        f"{len(gen)} GenAI spans", "Wrap LLM calls with otelkit.genai_call(system, model) and call .record(in, out).")
    return out


def score(results: list[Result]) -> int:
    total = sum(r.weight for r in results)
    return round(100 * sum(r.weight for r in results if r.passed) / total) if total else 0
