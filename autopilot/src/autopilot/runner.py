"""Start the app + stub against an in-process collector, drive traffic, return results."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .checks import run_checks, score
from .receiver import Collector


def _wait(url: str, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            httpx.get(url, timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"timeout waiting for {url}")


def verify(app_dir: str, traffic_file: str | None = None, app_port: int = 8000, stub_port: int = 8001) -> dict:
    app_dir = Path(app_dir).resolve()
    traffic = json.loads(Path(traffic_file or app_dir.parent / "traffic.json").read_text())
    col = Collector().start()
    env = {**os.environ,
           "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{col.port}",
           "OTEL_BSP_SCHEDULE_DELAY": "300", "OTEL_METRIC_EXPORT_INTERVAL": "1000",
           "PAYMENTS_URL": f"http://127.0.0.1:{stub_port}", "PYTHONUNBUFFERED": "1"}
    procs = []
    try:
        for mod, port in (("payments_stub:app", stub_port), ("app:app", app_port)):
            # the stub is a separate (uninstrumented) service; only the app under test exports
            e = dict(env)
            if mod.startswith("payments"):
                e.pop("OTEL_EXPORTER_OTLP_ENDPOINT")
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", mod, "--port", str(port), "--log-level", "warning"],
                cwd=app_dir, env=e, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        _wait(f"http://127.0.0.1:{stub_port}/openapi.json")
        _wait(f"http://127.0.0.1:{app_port}/openapi.json")
        base = f"http://127.0.0.1:{app_port}"
        with httpx.Client(timeout=10) as c:
            for r in traffic["requests"]:
                for _ in range(r.get("repeat", 1)):
                    c.request(r["method"], base + r["path"], json=r.get("json"))
        time.sleep(1.5)
        procs[1].send_signal(signal.SIGTERM)  # graceful shutdown flushes exporters
        procs[1].wait(timeout=10)
        time.sleep(0.5)
        results = run_checks(col.spans, traffic)
        total_requests = sum(r.get("repeat", 1) for r in traffic["requests"])
        db_spans = sum("db.system" in s["attrs"] for s in col.spans)
        return {"app": str(app_dir), "score": score(results), "spans": len(col.spans),
                "db_spans": db_spans, "db_spans_per_request": round(db_spans / max(total_requests, 1), 1),
                "metric_exports": col.metric_requests, "checks": [r.to_dict() for r in results]}
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        col.stop()


def load(app_dir: str, seconds: int = 60, endpoint: str = "http://127.0.0.1:4318", traffic_file: str | None = None,
         app_port: int = 8000, stub_port: int = 8001):
    """Run the app against a real collector and generate steady traffic (for dashboards)."""
    app_dir = Path(app_dir).resolve()
    traffic = json.loads(Path(traffic_file or app_dir.parent / "traffic.json").read_text())
    env = {**os.environ, "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint, "OTEL_METRIC_EXPORT_INTERVAL": "5000",
           "PAYMENTS_URL": f"http://127.0.0.1:{stub_port}"}
    procs = []
    try:
        for mod, port in (("payments_stub:app", stub_port), ("app:app", app_port)):
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", mod, "--port", str(port), "--log-level", "warning"],
                cwd=app_dir, env=env, stdout=subprocess.DEVNULL))
        _wait(f"http://127.0.0.1:{stub_port}/openapi.json")
        _wait(f"http://127.0.0.1:{app_port}/openapi.json")
        end, n = time.time() + seconds, 0
        with httpx.Client(timeout=10) as c:
            while time.time() < end:
                for r in traffic["requests"]:
                    c.request(r["method"], f"http://127.0.0.1:{app_port}" + r["path"], json=r.get("json"))
                    n += 1
                time.sleep(0.3)
        print(f"sent {n} requests over {seconds}s")
    finally:
        for p in procs:
            p.terminate()
