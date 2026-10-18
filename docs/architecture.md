# Architecture

Detail behind the [README](../README.md).

### System context (C4 level 1)

```mermaid
flowchart LR
    dev([Engineer / consultant])
    agent[Coding agent<br/>Claude Code, Cursor, etc.]
    core[otel-autopilot<br/>Skills + MCP server + otel-kit + verifier + dashboard generator]
    svc[Client service<br/>messy, uninstrumented]
    be[Observability backend<br/>Grafana stack, vendor-neutral OTLP]
    dev -->|asks for instrumentation| agent
    agent -->|reads skills, calls tools| core
    agent -->|edits code, opens PR| svc
    core -->|runs + scores| svc
    core -->|pushes dashboards, queries| be
    svc -->|OTLP telemetry| be
    dev -->|reviews PR + dashboards| be
```

### Containers (C4 level 2)

```mermaid
flowchart TB
    subgraph agentside [Agent side]
        agent[Coding agent]
        skills["skills/<br/>otel-instrument<br/>otel-verify<br/>otel-dashboards<br/>(markdown procedure + gotchas)"]
    end
    subgraph pkg [autopilot package]
        mcp["MCP server<br/>verify_instrumentation<br/>query_prometheus<br/>search_traces<br/>generate_dashboards"]
        ver["Verifier<br/>OTLP receiver + 9 checks + score"]
        dash["dashgen<br/>standard (library panels)<br/>one-off (discovered)"]
    end
    subgraph app [Service under test]
        code["FastAPI app<br/>sample-app/"]
        kit["otel-kit<br/>init() + scrubbing + GenAI helpers<br/>over OpenTelemetry SDK"]
    end
    subgraph stack [docker-compose backend]
        col["OTel Collector<br/>spanmetrics connector"]
        tempo[(Tempo<br/>traces)]
        prom[(Prometheus<br/>metrics)]
        graf[Grafana]
    end
    gmcp["mcp-grafana (official)"]

    agent -- reads --> skills
    agent -- tool calls --> mcp
    agent -- tool calls --> gmcp
    agent -- edits --> code
    code --> kit
    mcp --> ver
    mcp --> dash
    ver -- "starts app + traffic, receives OTLP" --> code
    kit -- OTLP/HTTP --> col
    kit -. "OTLP/HTTP (verify runs only)" .-> ver
    col --> tempo
    col -- "metrics + span metrics" --> prom
    graf --> tempo
    graf --> prom
    dash -- "Grafana API: library panels + dashboards" --> graf
    dash -- "discovers routes, DB, GenAI" --> prom
    gmcp --> graf
    mcp -- "PromQL, TraceQL" --> prom
    mcp --> tempo
```


## One demo run (sequence)

```mermaid
sequenceDiagram
    actor P as Presenter
    participant D as demo.sh
    participant A as Coding agent
    participant V as Verifier
    participant S as Service
    participant B as Backend
    P->>D: demo/demo.sh agent
    D->>V: verify (before)
    V->>S: start + drive traffic.json
    V-->>D: 0/100, no spans
    D->>A: instrument with otel-instrument skill
    A->>S: edit code (init, spans, error recording)
    A->>V: verify_instrumentation (MCP)
    V-->>A: score + fix hints
    A-->>D: 100/100 + instrumentation-plan.md
    D->>V: verify (after)
    V-->>D: 100/100
    D->>B: docker compose up
    D->>S: autopilot load
    S->>B: OTLP traces + metrics
    D->>B: dash standard / oneoff / push
    D-->>P: Grafana URLs
    D->>S: swap N+1 for join, verify again
    V-->>P: DB spans/request drops (15 to 0.3)
```

## Pieces

| Path | What it is |
|---|---|
| `skills/` | Vendor-neutral agent skills in plain markdown: discover, instrument, verify, dashboards. Include gotchas and "stop and ask a human" rules |
| `autopilot/` | `autopilot verify` (receiver, checks, score, CI gate via `--min-score`), `autopilot load`, `autopilot dash`, and the MCP server |
| `otel-kit/` | Thin, config-only distro: one `init()`, PII/secret scrubbing, GenAI and business-span helpers. Does not wrap the OTel API |
| `sample-app/` | `messy/` (the input), `reference/` (the target), `reference-fixed/` (N+1 fixed), `traffic.json` |
| `stack/`, `docker-compose.yml` | Collector with span metrics, Tempo, Prometheus, Grafana (images pinned) |
| `.mcp.json` | Registers our MCP server and Grafana's official `mcp-grafana` |
| `demo/demo.sh`, `demo/eval.sh` | The demo; and an eval harness that runs the agent N times and reports first-pass success |
| `dashboards/` | Generated dashboard JSON, committed so changes are reviewable |

### What the verifier checks (weights sum to 100)
Spans arrive (5), `service.name` (10), version and environment (5), a SERVER span with `http.route` for every endpoint (15), route-template span names (10), DB spans (10), outbound HTTP linked to the request trace (10), failures recorded as ERROR plus exception (15), no PII or secrets in attributes (10), GenAI attributes and token usage (10).


## Design notes
- **MCP vs skills:** skills carry procedure and knowledge (portable markdown). MCP covers live actions: verifying, confirming data landed, dashboards. Code edits stay with the agent's own file tools.
- **Thin distro:** `otel-kit` is config-only plus helpers. It never wraps the OTel API, so there is no lock-in and no key-person risk.
- **Dashboards:** library panels can only be created via the Grafana API, not file provisioning, so `autopilot dash push` uses the API and updates panels in place.
- **Verifier receiver:** an in-process OTLP/HTTP receiver, so verification needs no Docker and can run in CI.
