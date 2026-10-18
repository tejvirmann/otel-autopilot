from __future__ import annotations

import argparse
import json
import sys

from .report import render
from .runner import verify


def main(argv=None):
    p = argparse.ArgumentParser(prog="autopilot")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="run the app + traffic against a collector and score the telemetry")
    v.add_argument("app_dir")
    v.add_argument("--traffic")
    v.add_argument("--json", action="store_true")
    v.add_argument("--min-score", type=int, default=0, help="exit 1 below this score (CI gate)")
    l = sub.add_parser("load", help="run the app against the real collector and generate traffic")
    l.add_argument("app_dir")
    l.add_argument("--seconds", type=int, default=60)
    d = sub.add_parser("dash", help="generate Grafana dashboards as code")
    d.add_argument("what", choices=["standard", "oneoff", "push"])
    d.add_argument("--service")
    d.add_argument("--report", help="verify report JSON used to tailor a one-off dashboard")
    d.add_argument("--out", default="dashboards/out")
    d.add_argument("--grafana", default="http://localhost:3000")
    d.add_argument("--auth", default="admin:admin")
    a = p.parse_args(argv)
    if a.cmd == "verify":
        rep = verify(a.app_dir, a.traffic)
        print(json.dumps(rep, indent=2) if a.json else render(rep, sys.stdout.isatty()))
        sys.exit(0 if rep["score"] >= a.min_score else 1)
    if a.cmd == "load":
        from .runner import load
        return load(a.app_dir, a.seconds)
    from . import dashgen
    dashgen.cli(a)


if __name__ == "__main__":
    main()
