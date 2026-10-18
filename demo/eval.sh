#!/usr/bin/env bash
# Eval harness: run the agent N times on the golden messy repo and report first-pass scores.
# Turns "AI is flaky" into a number. Usage: demo/eval.sh [N]   (each run costs LLM tokens)
set -uo pipefail
cd "$(dirname "$0")/.."
N="${1:-5}"; scores=()
for i in $(seq 1 "$N"); do
  W=demo/eval-workspace/run-$i; rm -rf "$W"; mkdir -p "$W"; cp -R sample-app/messy "$W/shop-api"; cp sample-app/traffic.json "$W/"
  mkdir -p "$W/shop-api/.claude" && cp -R skills "$W/shop-api/.claude/skills" && cp .mcp.json "$W/shop-api/.mcp.json"
  ( cd "$W/shop-api" && claude -p "Use the otel-instrument skill to instrument this service. Verify with: uv run --project $PWD/../../../.. autopilot verify . . Write instrumentation-plan.md. Do not fix N+1 queries." \
      --permission-mode acceptEdits --allowedTools "Bash(uv run:*)" "Bash(cat:*)" "Read" "Edit" "Write" >/dev/null 2>&1 )
  s=$(uv run autopilot verify "$W/shop-api" --json | python3 -c "import sys,json;print(json.load(sys.stdin)['score'])")
  echo "run $i: score $s"; scores+=("$s")
done
printf '%s\n' "${scores[@]}" | awk '{s+=$1; if($1>=90)ok++} END{printf "mean %.0f, >=90 in %d/%d runs (first pass, no human fixes)\n", s/NR, ok, NR}'
