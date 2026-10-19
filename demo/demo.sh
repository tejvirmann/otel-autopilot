#!/usr/bin/env bash
# otel-autopilot demo. Run `demo/demo.sh help` for commands.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
W=demo/workspace
TOTAL=8
START=$(date +%s)

if [ -t 1 ]; then B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; E=$'\033[0m'
else B= D= G= Y= R= C= E=; fi

usage() {
  cat <<EOF
${B}otel-autopilot demo${E}

  demo/demo.sh replay        Run the whole demo with a pre-written solution (no AI, deterministic)
  demo/demo.sh agent         Run the whole demo with Claude Code doing the instrumenting (live, ~2-3 min, small LLM cost)
  demo/demo.sh setup         Only the preflight checks (uv sync, Docker, ports)
  demo/demo.sh open          Open Grafana dashboards in your browser
  demo/demo.sh reset         Clean up a run: kill leftover servers, delete demo/workspace
  demo/demo.sh reset --full  Also stop and wipe the Grafana/Tempo/Prometheus stack (clean graphs)
  demo/demo.sh down          Stop the backend stack

Options (environment variables):
  DEMO_PAUSE=1     wait for Enter between steps (for presenting live)
  DEMO_NO_OPEN=1   do not auto-open the browser
EOF
}

# ---------- helpers ----------
die()  { echo "${R}${B}ERROR:${E} $*" >&2; exit 1; }
note() { echo "  ${D}$*${E}"; }
cmd()  { echo "  ${D}\$ $*${E}"; }
run()  { cmd "$*"; "$@"; }
indent() { sed 's/^/    /'; }
STEP=0
step() {  # step "title" "what this shows"
  STEP=$((STEP+1))
  echo; echo "${B}${C}[$STEP/$TOTAL]${E}${B} $1${E}"
  [ -n "${2:-}" ] && echo "  $2"
  return 0
}
pause() { if [ -n "${DEMO_PAUSE:-}" ]; then read -rp "  ${D}press Enter to continue${E} " _; fi; return 0; }
port_free() { ! (echo > /dev/tcp/127.0.0.1/"$1") 2>/dev/null; }
wait_for() {  # wait_for <name> <url>
  for _ in $(seq 1 90); do curl -s -o /dev/null --max-time 2 "$2" && { note "up: $1"; return 0; }; sleep 1; done
  docker compose ps; die "$1 did not come up at $2 within 90s. Try: docker compose logs"
}
have_docker() { docker info >/dev/null 2>&1; }
open_url() { [ -n "${DEMO_NO_OPEN:-}" ] && return 0; if command -v open >/dev/null; then open "$1"; elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1; fi; return 0; }

kill_stale() {
  for p in 8000 8001; do
    for pid in $(lsof -ti :$p 2>/dev/null || true); do  # only our own leftover uvicorn servers, never anything else
      if ps -p "$pid" -o command= | grep -q uvicorn; then note "killing leftover uvicorn on port $p"; kill "$pid" 2>/dev/null || true; fi
    done
  done; return 0
}

preflight() {
  command -v uv >/dev/null || die "uv is not installed. See https://docs.astral.sh/uv/"
  run uv sync --quiet
  have_docker || die "Docker is not running. Start it (Docker Desktop, or: colima start) and retry."
  note "docker: running"
  for p in 8000 8001; do port_free $p || die "port $p is in use (a leftover run?). Run: demo/demo.sh reset"; done
  note "ports 8000/8001: free"
  if [ "${1:-}" = agent ]; then command -v claude >/dev/null || die "the 'claude' CLI is not installed (needed for agent mode). Use: demo/demo.sh replay"; note "claude CLI: $(command -v claude)"; fi
}

# ---------- commands ----------
cmd_reset() {
  kill_stale
  rm -rf "$W" demo/eval-workspace; note "removed demo/workspace"
  if [ "${1:-}" = "--full" ]; then have_docker && docker compose down -v 2>&1 | tail -1 || true; note "backend stack stopped and wiped"; fi
  echo "${G}reset done${E}"
}

cmd_open() {
  open_url http://localhost:3000/d/otel-standard-red/service-overview-standard?var-service=shop-api
  open_url http://localhost:3000/d/otel-oneoff-shop-api/shop-api-generated
}

cmd_run() {
  MODE="$1"
  echo "${B}otel-autopilot demo${E}  ·  mode: ${B}$( [ "$MODE" = agent ] && echo "AGENT (live AI)" || echo "REPLAY (no AI)" )${E}  ·  $TOTAL steps"
  if [ "$MODE" = agent ]; then
    echo "  Claude Code reads the skills in skills/, edits the service, and checks its own work with the verifier."
    echo "  Results vary run to run. Expect ~2-3 minutes and a small LLM cost (~\$0.50)."
  else
    echo "  ${Y}Replay applies a pre-written solution (sample-app/reference/app.py). No AI is involved.${E}"
    echo "  It shows the pipeline (verify, backend, dashboards) deterministically; it does not show the AI."
  fi

  step "Preflight" "Install dependencies and check Docker and ports."
  preflight "$MODE"; pause

  step "Reset" "Fresh copy of the messy service in $W/ (the original in sample-app/ is never touched)."
  kill_stale
  rm -rf "$W" && mkdir -p "$W" && cp -R sample-app/messy "$W/shop-api" && cp sample-app/traffic.json "$W/" && rm -f "$W/shop-api/shop.db"
  note "service: $W/shop-api   (no telemetry, swallowed errors, N+1 queries, string-built SQL)"; pause

  step "BEFORE: how observable is it?" "The verifier starts the service, sends traffic, and scores the telemetry it emits (0-100)."
  run uv run autopilot verify "$W/shop-api" 2>&1 | indent || true; pause

  if [ "$MODE" = agent ]; then
    step "AI instruments the service" "Claude Code runs headless inside $W/shop-api. Watch its tool calls below."
    mkdir -p "$W/shop-api/.claude" && cp -R skills "$W/shop-api/.claude/skills"
    cat > "$W/shop-api/.mcp.json" <<JSON
{"mcpServers": {"otel-autopilot": {"command": "uv", "args": ["run", "--project", "$ROOT", "autopilot-mcp"]}}}
JSON
    note "skills copied to $W/shop-api/.claude/skills (Claude Code auto-discovers them)"
    note "MCP server configured in $W/shop-api/.mcp.json"
    PROMPT="Use the otel-instrument skill to instrument this service. The otelkit library and the verifier live in the uv project at $ROOT: run python and the CLI via 'uv run --project $ROOT ...'. Verify with the verify_instrumentation MCP tool (app_dir = this directory), or fall back to: uv run --project $ROOT autopilot verify . . Write instrumentation-plan.md. Do not fix N+1 queries."
    note "prompt: ${PROMPT:0:120}..."
    echo
    ( cd "$W/shop-api" && claude -p "$PROMPT" --permission-mode acceptEdits --setting-sources project \
        --strict-mcp-config --mcp-config .mcp.json \
        --allowedTools "mcp__otel-autopilot__verify_instrumentation" "Bash(uv run:*)" "Bash(ls:*)" "Bash(cat:*)" "Read" "Edit" "Write" "Skill" \
        --output-format stream-json --verbose < /dev/null 2>/dev/null | python3 "$ROOT/demo/stream.py" )
  else
    step "'AI' instruments the service (replay)" "Copies a pre-written solution over app.py. Nothing is figured out here: this is a recording of what the agent produces."
    cp sample-app/reference/app.py "$W/shop-api/app.py"
    cat > "$W/shop-api/instrumentation-plan.md" <<'PLAN'
# Instrumentation plan (replayed reference solution)
- otelkit.init() at startup: resource attrs, OTLP export, PII scrubbing, FastAPI/httpx/sqlite3 auto-instrumentation.
- business_span around checkout; payment failure now recorded as ERROR + exception (was swallowed).
- genai_call around the LLM call with token usage.
- sqlite3: switched connection.execute() to cursor().execute() (the shortcut is not traced).
- Not changed: N+1 queries in /products, string-built SQL in /users/lookup (flagged for follow-up).
PLAN
  fi
  echo; echo "  ${B}What changed in app.py:${E}"
  diff -u sample-app/messy/app.py "$W/shop-api/app.py" | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' | head -40 | indent || true
  note "full explanation: $W/shop-api/instrumentation-plan.md"; pause

  step "AFTER: verify again" "Same service, same traffic, same verifier. Did the instrumentation actually work?"
  run uv run autopilot verify "$W/shop-api" 2>&1 | indent; pause

  step "Start the real backend and send traffic" "Collector, Tempo (traces), Prometheus (metrics), Grafana (dashboards) in Docker; then 30s of traffic."
  run docker compose up -d 2>&1 | tail -1 | indent || die "docker compose up failed (are ports 3000, 3200, 4317, 4318, 8889, 9090 free?)"
  wait_for "OTel Collector" http://127.0.0.1:4318/
  wait_for "Prometheus" http://127.0.0.1:9090/-/ready
  wait_for "Tempo" http://127.0.0.1:3200/ready
  wait_for "Grafana" http://127.0.0.1:3000/api/health
  run uv run autopilot load "$W/shop-api" --seconds 30; pause

  step "Generate dashboards as code and push them to Grafana" "7 shared library panels + a \$service-templated dashboard, plus one tailored to what this service emits."
  run uv run autopilot dash standard --out dashboards/out | indent
  run uv run autopilot dash oneoff --service shop-api --out dashboards/out-oneoff | indent
  run uv run autopilot dash push --out dashboards/out | indent
  run uv run autopilot dash push --out dashboards/out-oneoff | indent
  echo
  echo "  ${B}LOOK AT GRAFANA NOW${E} (no login needed):"
  echo "    standard dashboard : ${C}http://localhost:3000/d/otel-standard-red/service-overview-standard?var-service=shop-api${E}"
  echo "    one-off dashboard  : ${C}http://localhost:3000/d/otel-oneoff-shop-api/shop-api-generated${E}"
  echo "    traces (Tempo)     : http://localhost:3000/explore  -> choose Tempo -> Search -> service.name = shop-api"
  [ -z "${DEMO_NO_OPEN:-}" ] && { note "opening the dashboards in your browser (set DEMO_NO_OPEN=1 to skip)"; cmd_open; }
  echo "  ${Y}Keep that tab open: the next step changes the data and the panels refresh every 10s.${E}"; pause

  step "Payoff: the traces exposed a bug. Fix it and compare." "Instrumenting revealed an N+1 query: ~15 database calls per /products request."
  note "database calls per request BEFORE the fix:"
  uv run autopilot verify "$W/shop-api" 2>/dev/null | grep "DB spans" | indent || note "(could not measure DB spans)"
  cp sample-app/reference-fixed/app.py "$W/shop-api/app.py"
  note "replaced the N+1 loop with one JOIN query (sample-app/reference-fixed/app.py), then:"
  uv run autopilot verify "$W/shop-api" 2>/dev/null | grep "DB spans" | indent || note "(could not measure DB spans)"
  note "sending 30s more traffic so the dashboard shows the change:"
  uv run autopilot load "$W/shop-api" --seconds 30

  SECS=$(( $(date +%s) - START ))
  echo; echo "${G}${B}Demo complete${E} in ${SECS}s."
  cat <<EOF

  ${B}Where to look${E}
    Grafana dashboards  http://localhost:3000  (Dashboards -> Browse -> tag "otel-autopilot")
      - "DB spans per request" panel drops after the fix; "/products" p95 latency drops too
    The AI's work       $W/shop-api/app.py and $W/shop-api/instrumentation-plan.md
    Generated dashboards-as-code   dashboards/out/ and dashboards/out-oneoff/

  ${B}Next${E}
    demo/demo.sh open          re-open the dashboards
    demo/demo.sh reset         clean up for another run (add --full for clean graphs)
    demo/demo.sh down          stop the backend
EOF
}

case "${1:-help}" in
  replay|agent) cmd_run "$1" ;;
  setup)  STEP=0; TOTAL=1; step "Preflight"; preflight "${2:-}"; echo "${G}ready${E}" ;;
  open)   cmd_open ;;
  reset)  cmd_reset "${2:-}" ;;
  down)   docker compose down ;;
  help|-h|--help) usage ;;
  *) usage; exit 1 ;;
esac
