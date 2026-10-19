#!/usr/bin/env python3
"""Pretty-print `claude -p --output-format stream-json` so a viewer can follow what the agent is doing."""
import json, os, re, sys

D, B, G, Y, C, E = "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"
if not sys.stdout.isatty():
    D = B = G = Y = C = E = ""
cwd = os.getcwd()
pending = {}


def short(p):
    return p.replace(cwd + "/", "").replace(os.path.expanduser("~"), "~")


def out(tag, msg, color=""):
    print(f"  {color}{tag:<8}{E} {msg}", flush=True)


for line in sys.stdin:
    try:
        e = json.loads(line)
    except ValueError:
        continue
    t = e.get("type")
    if t == "system" and e.get("subtype") == "init":
        mcp = {m["name"]: m["status"] for m in e.get("mcp_servers", [])}
        skills = [s for s in e.get("skills", []) if s.startswith("otel-")]
        out("setup", f"Claude Code {e.get('claude_code_version')} · model {e.get('model')}", D)
        out("setup", f"project skills loaded: {', '.join(skills) or 'NONE'}", D)
        out("setup", f"MCP otel-autopilot: {mcp.get('otel-autopilot', 'not configured')}", D)
    elif t == "assistant":
        for c in e["message"]["content"]:
            if c["type"] == "text" and c["text"].strip():
                out("claude", c["text"].strip().replace("\n", " ")[:220], C)
            elif c["type"] == "tool_use":
                n, i = c["name"], c["input"]
                pending[c["id"]] = n
                if n == "Skill":
                    out("skill", f"loading skill '{i.get('skill')}' (its SKILL.md instructions enter the agent's context)", Y)
                elif n in ("Read", "Edit", "Write"):
                    out(n.lower(), short(i.get("file_path", "")), B if n != "Read" else D)
                elif n == "Bash":
                    out("run", short(i.get("command", "")).replace("\n", " ")[:150], D)
                elif n.startswith("mcp__"):
                    out("mcp", n.split("__", 2)[-1], Y)
                else:
                    out(n.lower(), "", D)
    elif t == "user":
        content = e.get("message", {}).get("content", [])
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_result":
                body = c.get("content")
                body = " ".join(x.get("text", "") for x in body) if isinstance(body, list) else str(body)
                m = re.search(r"Instrumentation score: (\d+)/100", body)
                if m:
                    out("verify", f"score {m.group(1)}/100", G if m.group(1) == "100" else Y)
    elif t == "result":
        print()
        out("done", f"{e.get('num_turns')} turns · {e.get('duration_ms', 0) / 1000:.0f}s · ${e.get('total_cost_usd', 0):.2f}"
            + (" · ERROR" if e.get("is_error") else ""), G)
