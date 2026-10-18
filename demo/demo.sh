#!/usr/bin/env bash
# Reproducible demo. Usage: demo/demo.sh [agent|replay]   (default: replay)
#   agent  - Claude Code does the instrumentation live using the skills + MCP server
#   replay - applies the reference solution (deterministic; same story, no LLM variance)
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-replay}"
W=demo/workspace
B=$'\033[1m'; D=$'\033[2m'; E=$'\033[0m'
step() { echo; echo "${B}== $* ==${E}"; }
pause() { [ -n "${DEMO_PAUSE:-}" ] && read -rp "${D}[enter to continue]${E} " _ || true; }

step "0. Reset: fresh copy of the messy service"
rm -rf "$W" && mkdir -p "$W" && cp -R sample-app/messy "$W/shop-api" && cp sample-app/traffic.json "$W/"
rm -f "$W/shop-api/shop.db"; echo "service: $W/shop-api (no telemetry, swallowed errors, N+1 queries, raw SQL)"; pause

step "1. BEFORE: how observable is it?"
uv run autopilot verify "$W/shop-api" || true; pause

step "2. AI instruments it ($MODE mode)"
if [ "$MODE" = agent ]; then
  mkdir -p "$W/shop-api/.claude" && cp -R skills "$W/shop-api/.claude/skills" && cp .mcp.json "$W/shop-api/.mcp.json"
  ( cd "$W/shop-api" && claude -p "Use the otel-instrument skill to instrument this service. Verify with: uv run --project $PWD/../../.. autopilot verify . . Write instrumentation-plan.md. Do not fix N+1 queries." \
      --permission-mode acceptEdits --allowedTools "Bash(uv run:*)" "Bash(cat:*)" "Read" "Edit" "Write" )
else
  cp sample-app/reference/app.py "$W/shop-api/app.py"
  cat > "$W/shop-api/instrumentation-plan.md" <<'PLAN'
# Instrumentation plan (replayed reference solution)
- otelkit.init() at startup: resource attrs, OTLP export, PII scrubbing, FastAPI/httpx/sqlite3 auto-instrumentation.
- business_span around checkout; payment failure now recorded as ERROR + exception (was swallowed).
- genai_call around the LLM call with token usage.
- sqlite3: switched connection.execute() to cursor().execute() (the shortcut is not traced).
- Not changed: N+1 queries in /products, string-built SQL in /users/lookup (flagged for follow-up).
PLAN
  diff -u sample-app/messy/app.py "$W/shop-api/app.py" | sed 's/^/    /' | head -60 || true
fi; pause

step "3. AFTER: verify (same traffic, now through the verifier)"
uv run autopilot verify "$W/shop-api"; pause

step "4. Real backend: start Grafana/Tempo/Prometheus/Collector"
docker compose up -d >/dev/null && sleep 6
uv run autopilot load "$W/shop-api" --seconds 30; pause

step "5. Dashboards as code (standard library-panel dashboard + one-off)"
uv run autopilot dash standard --out dashboards/out
uv run autopilot dash oneoff --service shop-api --out dashboards/out-oneoff
uv run autopilot dash push --out dashboards/out
uv run autopilot dash push --out dashboards/out-oneoff
echo "open: http://localhost:3000/d/otel-standard-red   and   http://localhost:3000/d/otel-oneoff-shop-api"; pause

step "6. Payoff: telemetry exposes the N+1, fix it, compare"
echo "DB spans per request before the fix:"; uv run autopilot verify "$W/shop-api" | grep "DB spans"
cp sample-app/reference-fixed/app.py "$W/shop-api/app.py"
echo "after replacing the N+1 with a join:"; uv run autopilot verify "$W/shop-api" | grep "DB spans"
uv run autopilot load "$W/shop-api" --seconds 30
echo; echo "Watch the 'DB spans per request' panel drop in Grafana."
