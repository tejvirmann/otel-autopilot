from __future__ import annotations

GREEN, RED, DIM, BOLD, END = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def render(rep: dict, color: bool = True) -> str:
    c = (lambda s, k: f"{k}{s}{END}") if color else (lambda s, k: s)
    lines = [c(f"Instrumentation score: {rep['score']}/100", BOLD) + c(f"  ({rep['spans']} spans received)", DIM)]
    for r in rep["checks"]:
        mark = c("PASS", GREEN) if r["passed"] else c("FAIL", RED)
        lines.append(f"  {mark}  {r['title']} {c('[' + str(r['weight']) + ']', DIM)}")
        lines.append(c(f"        {r['detail']}", DIM))
        if r["fix"]:
            lines.append(f"        fix: {r['fix']}")
    if rep.get("db_spans"):
        lines.append(c(f"  info  {rep['db_spans']} DB spans, {rep['db_spans_per_request']} per request (high = N+1 suspect)", DIM))
    return "\n".join(lines)
