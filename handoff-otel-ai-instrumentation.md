# Handoff: AI-Assisted OpenTelemetry Instrumentation Pitch for Xorbix

Written 2026-10-17 as a context brief for another agent. It covers the situation, what we want to create, why, what is decided, and what is still open.

---

## 1. The situation

**Who:** Tejvir Mann, a software engineer, is pursuing a role or project engagement with **Xorbix** (a technology services firm). His contact is **Tom Campbell, Chief Technology Officer**.

**What we know about Tom's interest:** Tejvir reports Tom seems interested in using AI for OpenTelemetry (OTel), observability, and monitoring.

**Email timeline (all 2026):**
- Early October: Tom told Tejvir to reach out with a salary range. Tejvir replied offering a flexible range of **$80K-$140K** depending on scope, said he is open to a **project-based arrangement**, and pitched a product idea: a simple way for teams to use their existing agents to instrument and observe their applications. He mentioned a similar observability offering from the Strudel AI team in Madison.
- Oct 6: Tejvir followed up. Tom replied the same day: he got the email, needs to discuss internally, first needs to **finalize the software requirements** (expected that week), and would **reach out the following week**.
- Oct 7: Tejvir acknowledged.
- Oct 14: Tejvir followed up again asking how requirements were going. **No reply from Tom as of Oct 17.**

**Implication:** Tejvir has already followed up several times. Another plain status check would be low value. Anything he sends next should add something new (for example a concept one-pager, a demo, or one sharp question).

**Unknown and important:** What Tom's "software requirements" are for (internal product vs. client engagement) and what stack Xorbix or its clients primarily use. A web search to confirm Xorbix's stack was inconclusive. Do not assume a stack.

---

## 2. The goal

Create material that makes Tejvir's value **concrete and convincing to Tom**, in a form Tom can **forward to others and advocate from internally**. Specifically:

1. **An ADR (Architecture Decision Record)** describing the proposed design.
2. **A working demo** with the design built out.
3. **A demo walkthrough:** take a messy codebase and visibly do the work (instrument, verify, dashboards, diagnose a fault).
4. **A business case / one-pager** with KPIs and a financial argument Tom can reuse.

**Current status:** The user explicitly chose to **iron out the idea and understand Tom's perspective before building anything.** Nothing has been built yet. Do not start building the demo unless the user says so.

**User's earlier format/stack choices (to apply when building starts):**
- Reference app language: **Python / FastAPI**
- Backend: **Grafana stack** (Tempo, Prometheus, Loki, OTel Collector), vendor-neutral
- Docs: **ADR as markdown in the repo, plus a shareable doc** for Tom to forward

---

## 3. Why this idea (and why it is not trivially novel)

### The landscape: AI-assisted OTel instrumentation already exists
Found in web research on 2026-10-17. Verify details against current docs before citing.

- **Datadog:** An MCP server with an `onboarding` toolset. The user types a one-line prompt; the agent reads code, calls MCP tools with permission, applies changes, and verifies. Also an **AI Setup CLI** (`npx @datadog/ai-setup-cli`) that adds SDK initialization and is designed so a CI job or script can run it. Docs list Agent Observability support (OpenAI, Anthropic, LangChain, Vercel AI SDK) auto-detected from dependencies. This appears to target **Datadog's own setup**, not neutral OTel (not read end to end).
- **Honeycomb:** Open-source agent skills (OpenTelemetry Instrumentation, a six-phase Migration skill where context propagation is described as roughly 60% of effort, Production Investigation, Query Patterns), an Instrumentation Advisor agent, and MCP prompts such as `/honeycomb-onboarding`.
- **Observe:** Skills for auto-instrumentation, manual instrumentation, and validation (audit against OTel best practices).
- **Dash0:** Agent skills for instrumentation, semantic conventions, collector pipelines, OTTL; mentions an "instrumentation score" and PR checks.
- **Sematext:** A plain-markdown skill that asks six questions and produces an env-var block.
- **Open-source OTel MCP server for Kubernetes** (talkops): discovers, provisions, instruments, validates, and governs OTel pipelines via Instrumentation/Collector CRDs, with dry-run-first safety.
- **LLM-specific:** OpenLLMetry (Traceloop) and OpenLIT instrument LLM and MCP workloads on top of OTel.

### Consequence for positioning
"AI adds OTel to your app" **is commoditized and vendor-subsidized.** Pitching it as the product invites "why not use the vendor tools?" The credible differentiators are below.

### Differentiators to build the pitch around
1. **Vendor-neutral.** Most vendor tooling funnels to one backend. A consultancy serving many clients benefits from a stack-agnostic approach.
2. **Verification as the core product.** Not just generating code but proving telemetry is correct (running the app, driving traffic, asserting on what arrives at a collector).
3. **Dashboards as code** generated from discovered telemetry (not found in the vendor skills during research; not checked exhaustively).
4. **Eval harness for the skill itself.** Golden messy repos with known expected telemetry; run the agent repeatedly and measure first-pass success rate. This converts "AI is flaky" into a measurable, improvable number. Not seen in the vendor offerings.
5. **A repeatable consulting playbook** Xorbix can sell (e.g., fixed-price "observability readiness" engagement with a scorecard), rather than a tool.
6. **GenAI observability angle.** Clients building agents will need to see token usage, cost, tool calls, latency. Maps to OTel GenAI semantic conventions.

---

## 4. Proposed design (for the ADR)

### Components
1. **Thin distro (Python).** A single `init()` setting resource attributes (`service.name`, env, version), exporter and sampling defaults, PII/header scrubbing, plus a few helpers for business spans and GenAI calls. **It must not wrap the OTel API itself** (avoids hiding standard concepts, lock-in, and key-person risk). Config-only plus helpers.
2. **Vendor-neutral skills (markdown agent skills).** Discover, plan, instrument, verify, dashboard. Each has defined inputs/outputs and an explicit "stop and ask a human" rule. Output is a **PR plus an `instrumentation-plan.md`** explaining each decision so reviewers are not trusting a black box. Humans review and merge; no auto-merge.
3. **Verifier.** Runs the app plus a traffic generator against a collector, then asserts: required resource attributes present, spans on every route, DB and outbound calls traced, context propagated across services, errors recorded, no PII-looking attributes, cardinality within budget, semantic-convention conformance. Produces a score and JSON/markdown report; usable as a CI gate. Align with existing instrumentation-score conventions rather than inventing a new one where possible.
4. **Dashboards as code.** RED metrics per service (from span metrics) and SLO panels, as Grafana JSON provisioned automatically.
5. **Eval harness** for the skill (see differentiator 4).
6. **Later / optional:** an MCP server over Tempo/Prometheus/Loki for questions like "why was checkout slow at 2pm?"; modernization as a follow-on phase.

### MCP vs. skills (design rationale)
- **Skills** carry knowledge and procedure (which package to pick, what to avoid). Plain markdown, portable across coding agents.
- **MCP** is useful for live or stateful actions: querying the backend to confirm data landed (verification), cluster operations, guided prompts. It does **not** help with the code edits themselves, which the coding agent's own file tools handle.
- A strong design uses both.

### Wrapper library vs. plain OTel
Use both, but keep the wrapper thin. The skill targets one uniform entry point, so output is consistent and the verifier can check conformance against one known shape. Costs: per-language maintenance, and Tom may worry about dependency on one person. Mitigate by keeping it config-only. (This is design reasoning, not sourced.)

### Poor codebases and modernization
Instrument first, then modernize. Telemetry is the safety net: observe first (low risk), use traces to find hot paths, dead code, hidden dependencies and N+1 queries, then change code and compare to the baseline. Messy code makes instrumentation harder (swallowed exceptions, global state, no clear service boundaries, broken context propagation). Principle: **deterministic codemods for mechanical changes, AI for judgment calls, traces plus characterization tests as the regression check.** Candidate tools **from memory, verify before citing:** OpenRewrite (Java), jscodeshift (JS), ruff/pyupgrade/libcst (Python), Microsoft .NET upgrade tooling. For the demo, one small example is enough (traces reveal an N+1 query or dead endpoint).

---

## 5. Tom's likely perspective (inferred, not known)

Reasoned from his role as CTO of a services firm; treat as hypotheses to validate.

- Does it make or save money (billable offering, fixed-price margin, utilization)?
- Delivery risk: repeatable outcomes that do not depend on one consultant.
- Build vs. buy: why not free vendor tools?
- Trust and security: AI agents touching client code, PII in telemetry.
- Ownership: who maintains it if Tejvir leaves?
- Cost of saying yes: salaried hire vs. a small pilot.

**Questions to expect:** Why not vendor tools? How do we know the AI output is correct? What does a client engagement look like? How does it make money? What does it cost to try?

---

## 6. KPIs and financial argument

### Program KPIs (what gets reported)
- Time to first trace from repo handoff.
- Instrumentation coverage and verifier score, before and after.
- First-pass success rate (no human fixes) across the golden repos.
- Human review minutes per service.
- Runtime overhead from instrumentation, measured by load test.
- LLM token cost per service instrumented.
- On seeded faults, time to root cause with vs. without traces (illustrative only; small sample, label as such).

### Financial model (no invented numbers)
Give Tom a formula he fills in with Xorbix's real rates:

> Savings per service = (manual hours - assisted hours) x blended rate - (token cost + review hours x rate)

Multiply by services per engagement for engagement-level savings; divide the cost of the arrangement by savings per engagement for break-even. The demo supplies measured "assisted hours"; Tom supplies the rest.

### Revenue framing (stronger than cost-saving for a services firm)
- Fixed-price "observability readiness" engagement.
- Recurring scorecard as a retention hook.
- AI-observability offering for clients building agents.

**Still to do:** find one or two sourced industry figures on downtime cost and MTTR for context. Do not fabricate benchmarks.

---

## 7. Honest weaknesses to address up front

- Vendor tools are free and good; "AI instruments your app" alone does not differentiate.
- A demo on a toy app proves the approach, not scale on a real client codebase. Say so and propose a **real client pilot** as the actual test.
- AI instrumentation is sometimes wrong. The verifier and eval harness are the answer, which is why they are the center of the pitch.

---

## 8. Commercial framing for Tejvir

- His earlier $80K-$140K range signals flexibility but gives Tom no anchor. A **time-boxed paid pilot** (for example 3-4 weeks to productize this as a Xorbix offering) ties a number to a deliverable and lowers Tom's risk.
- Time-box the demo effort (about a week of work: one language, one sample app, one dashboard set). Do not over-invest before hearing from Tom.
- Send the demo or a concept one-pager as the next touchpoint, since it adds value instead of another status check.

---

## 9. Open questions

1. What are Tom's software requirements for (internal product vs. client engagement), and what is the primary stack? (Possibly ask Tom one sharp question.)
2. Does Tejvir want to lead with a role or a pilot/project arrangement?
3. Should the next step be a short note to Tom, an ADR outline for the user to react to, or the full build?

---

## 10. Guidance for the next agent

- **Do not build the demo yet.** The user wants to refine the idea and consider Tom's perspective first. Confirm scope before building.
- **Do not invent figures** (savings, downtime costs, benchmarks). Use measured values from the demo, a plug-in formula, and sourced stats.
- **Verify before citing:** vendor feature claims (re-check current docs) and the modernization tools listed from memory.
- **Be honest about environment limits:** the agent workspace may not be able to run the full Docker/Grafana stack. Build and test code, configs, and dashboard JSON where possible, and state exactly what could and could not be run. The user would run `docker compose up` locally to see it live.
- Keep Tom as the intended audience of anything produced: concise, credible, forwardable, with caveats stated plainly. A CTO will distrust inflated claims.
