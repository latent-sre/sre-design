# SRE Knowledge-Base Generator (`sre-design`)

## Context

We need a repo-neutral, enterprise system that performs a deep SRE review of an
arbitrary dev repository and emits a **populated, validated SRE knowledge base**,
then opens a PR uploading it into a pre-existing company SRE repo. The knowledge
base is also projected into **GitHub Copilot skills/agents** that engineers use
inside VS Code.

Two halves, confirmed with the user:

- **Python engine** — the *deterministic* half. Scans a locally-cloned target
  repo, extracts facts with hard provenance (file/line/commit/excerpt-hash),
  scaffolds schema-tagged YAML artifacts, **validates** them, renders Copilot
  skills, and opens the PR.
- **An LLM behind the `LLMProvider` seam** — the *judgment* half. The load-bearing
  rule is the trust invariant, not the transport: **the LLM is a pointer-generator,
  never a fact source** — it cites verbatim bytes; the engine re-grounds every output
  deterministically and gates it (downgrade-only). Transports plug into one seam
  (`llm/provider.py`): **GitHub Copilot in VS Code** is the default (file-exchange;
  the engine embeds no model), driven by the **Agent Skills / custom agent / prompt
  files this repo ships**; a **subprocess oracle** (any CLI via `--oracle`) and
  approved API providers (e.g. Vertex — see
  [`VERTEX-LLM-PROVIDER-CASE.md`](VERTEX-LLM-PROVIDER-CASE.md)) run the same worklist
  tasks programmatically. LLM-neutral throughout: no pinned model or vendor.

Backbone = **YAML artifacts with `apiVersion` + `kind`** (Kubernetes/Backstage
style), each validated against a JSON Schema. The KB-as-YAML is the single source
of truth; Copilot skills, the Backstage catalog, and dashboards are *projections*.

**Three neutralities:** repo-neutral (pluggable per-language collectors) ·
LLM-neutral (the `LLMProvider` seam; no pinned model/vendor) · SCM-neutral (a `Forge`
seam; GitHub implemented first because that is the company SCM).

**First deployment profile: on-prem VMs + PCF / Pivotal Cloud Foundry.** There,
`manifest.yml`, buildpacks, routes, service bindings (VCAP), Spring Cloud Config,
Eureka, Actuator, Micrometer, Resilience4j/Hystrix are first-class signals. The
platform is a profile, not the architecture: collectors are registry-driven
(`config/profiles/*`), so Kubernetes or cloud deployment descriptors are additional
profiles, not a redesign. Collectors ship for Java/Spring, .NET/Steeltoe,
Python/FastAPI, Node/Express, and Go.

**Confirmed decisions:** the LLM is a pointer-generator behind the `LLMProvider` seam,
never a fact source · first vertical slice = **Flow → Alert → Runbook** · publish to
**company GitHub** (neutral Forge) · alert/runbook backends are **pluggable render
adapters defined as data** (`alert-backends.md`), not architecture — currently
shipped: **Splunk** SPL, **Prometheus+Grafana** PromQL, **AppDynamics** health rules,
**Wavefront / VMware Aria Operations for Applications** ts(), and **ThousandEyes**;
adding a backend is a new adapter, not a design change.

---

## Implementation status

Live status is **not tracked here**. [`HYBRID-PLAN.md`](HYBRID-PLAN.md) is the single
source of truth (§8 the tracker, §9 the rolling reassessment);
[`SCOPE-AND-COVERAGE.md`](SCOPE-AND-COVERAGE.md) holds the coverage matrix and the
accuracy gates. This document records the architecture and its invariants.

---

## Architecture at a glance

```
            sre-design repo (the tool)
            ┌─────────────────────────────────────────────────────────┐
            │  Python engine (sre_kb)        Copilot skill/agent assets │
            │  collectors→facts→scaffold      .github/skills/*/SKILL.md    │
            │  validate→render→publish        .github/agents/*.agent.md   │
            │                                 .github/prompts/*.prompt.md │
            │                                 .github/copilot-instructions│
            └─────────────────────────────────────────────────────────┘
                         │ clone (local)                 ▲ run in VS Code
                         ▼                                │
   target dev repo ──► facts/ + scaffolded KB ──► Copilot agent enriches ──►
                         │                                                  │
                         └──► sre-kb validate (schema+provenance+crossref) ◄┘
                                          │ (loop until green)
                                          ▼
                       render Copilot projection + Backstage catalog
                                          ▼
                       open PR  ──►  company GitHub SRE repo
```

The `sre-analyst` custom agent (and the Agent Skills it uses) is wired with the
terminal tool so the **agent itself runs `sre-kb scan` / `sre-kb validate`** between
synthesis steps and self-corrects until validation is green. That closed loop is
what makes the KB *validated*.

---

## Repo layout (`sre-design`)

```
sre-design/
├── pyproject.toml                # packaging; console_script "sre-kb"; ruff+pytest
├── README.md, Makefile, .pre-commit-config.yaml
├── config/
│   ├── default.yaml              # gates, paths, enabled collectors
│   ├── profiles/java-spring-pcf.yaml
│   └── forges/github.yaml
├── schemas/                      # JSON Schema, Draft 2020-12
│   ├── _envelope.schema.json     # shared metadata/evidence/confidence/status
│   ├── v1alpha1/<Kind>.schema.json   (one per kind — see catalog)
│   └── registry.yaml             # kind → schema + collector + prompt + validator
├── prompts/                      # canonical analysis instructions (domain-versioned)
│   └── <domain>/v1/{template.md,examples.yaml}
├── .github/                      # the Copilot "skill/agent" driver (ships in tool repo)
│   ├── copilot-instructions.md           # repo-wide grounding (+ AGENTS.md, always-on)
│   ├── agents/sre-analyst.agent.md       # custom agent (the renamed "chat mode")
│   ├── skills/                           # Agent Skills — each a self-contained folder
│   │   └── sre-flow-analysis/
│   │       ├── SKILL.md                  # name + description (discovery) + body
│   │       ├── scripts/run.sh            # thin wrapper → `sre-kb scan/validate`
│   │       ├── references/{envelope.md,flow-schema.md,failure-modes.md,provenance-rules.md}
│   │       └── templates/flow.skeleton.yaml
│   └── prompts/{flow,alert,runbook}.prompt.md   # one-shot manual entrypoints
├── src/sre_kb/
│   ├── cli.py                    # Typer app; one subcommand per stage
│   ├── config.py                 # pydantic-settings (file + env overlay)
│   ├── models/{facts.py,envelope.py,artifacts.py}
│   ├── workspace/{clone.py,layout.py}
│   ├── collectors/
│   │   ├── base.py               # Collector protocol + registry + lang detection
│   │   ├── common/{fs_walk.py,manifest_pcf.py,dependency_lock.py}
│   │   └── java_spring/{build,annotations,config_props,resiliency,observability,flow_builder}.py
│   ├── flow/{callgraph.py,failure_modes.py,budget_check.py}  # +timeout/retry-budget check
│   ├── synth/{scaffold.py,context_pack.py}   # deterministic skeletons + Copilot context packs
│   ├── scoring/readiness.py          # PRR checks + KB-coverage scorecard
│   ├── validation/{structural,provenance,crossref,gating,report}.py
│   ├── render/{kb_writer,copilot,catalog,diagrams}.py   # +Mermaid sequence/topology
│   ├── publish/forge/{base.py,github.py}     # Forge protocol; GitHub first
│   ├── publish/pr_builder.py
│   └── pipeline/{stages.py,orchestrator.py,state.py}
├── output_templates/{copilot/*.j2, catalog/catalog-info.yaml.j2, pr/pr_body.md.j2}
└── tests/{fixtures/sample-spring-pcf/, unit/, golden/, e2e/}
```

**Ephemeral run dir** (git-ignored) — stages hand off via disk, so runs are
resumable and inspectable:

```
.work/<run-id>/  run.json · target/ · facts/ · candidates/ ·
                 kb/{verified,needs-review}/ · projections/ · reports/ · pr/
```

`facts/` = deterministic scan output · `candidates/` = scaffolded artifacts that
Copilot enriches **in place** (then validated) · `kb/` = post-validation, split by
status.

---

## The "validated KB" envelope (`_envelope.schema.json`)

Every artifact `$ref`s this. It is what distinguishes a *validated* KB from notes.

```yaml
apiVersion: sre.kb/v1alpha1
kind: <Kind>
metadata: { name, service, owner, domain, labels, annotations }
spec: { ...kind-specific... }
evidence:                       # citation integrity — ≥1 required to be "verified".
  - { repo, commit, path, lines: {start,end}, excerptHash: sha256:…, detector }
                                #   The hash proves the cited bytes exist verbatim; it
                                #   does not prove they support the claim (challenge pass
                                #   does), and on engine output it passes by construction.
confidence: 0.0–1.0             # signal strength, not a calibrated probability: DIRECT
                                #   (declared) > DERIVED (composed) > INFERRED > WEAK,
                                #   plus a corroboration bonus. Gating splits at 0.7.
status: verified | needs-review | rejected
provenanceMode: deterministic | llm-asserted
crossRefs: [ { kind, name, relation } ]    # implements/depends-on/alerts-on/mitigates
generatedBy: { tool, toolVersion, driver: "copilot"|"engine", promptVersion, generatedAt }
```

`excerptHash` (SHA-256 of the exact cited bytes at the scanned commit) is the
keystone: a Copilot-asserted citation that doesn't exist, or has drifted, **cannot
pass** the provenance validator and is auto-downgraded to `needs-review`.

### Schema lifecycle (`apiVersion: sre.kb/v1alpha1`)

The version string follows the Kubernetes API convention: **`v1alpha1` = experimental, no
compatibility promise**. While every kind sits at alpha:

- **Anything may change between engine versions** — fields renamed/removed, enums reshaped,
  kinds pruned (it already happened: 4 kinds removed in S1). A consumer pins the engine
  version it scanned with; the vendored `.sre/schemas` in the published repo are the
  authoritative contract *for that repo's artifacts*, which is what makes a KB self-describing
  even across engine upgrades.
- **What is stable even in alpha:** the envelope's load-bearing core — `apiVersion`/`kind`/
  `metadata.name`, `evidence[].excerptHash` semantics, the `status` vocabulary, and the
  downgrade-only gating contract. Tools may rely on these; everything under `spec` is
  per-kind and alpha.
- **Promotion to `v1beta1`** is the signal that external consumers (a Backstage ingest, an
  incident agent) may depend on `spec` shapes: it requires the eval scorecard floors of
  SCOPE §3 to hold, every kind to carry a golden example, and — from then on — additive-only
  changes within the version plus a documented conversion note for anything that moves.
  Until a second version exists, no conversion machinery is built (YAGNI); the registry
  (`schemas/registry.yaml`) is where a per-kind version would be declared when it does.

---

## Schema & `kind` catalog (maps every focus area)

| Focus area (user) | `kind` | Key `spec` | Slice? |
|---|---|---|---|
| Tech stack | `TechStack` | languages/frameworks (+version+source), runtime, buildTool, pcf{buildpack,stack} | P2 |
| Architecture (+ design patterns) | `Architecture` | components, layers, boundaries, styleTags, **patterns (CQRS/Saga/…)**, c4Level | P2 |
| Infra + deployment + capacity | `Deployment` | hosting (**VM**\|**PCF**), org/space, unit (jar/war/buildpack), startCommand, routes, envBindings, **instances/mem/disk limits + pool sizes (capacity)**, stack, healthCheck, manifestPath | P2 |
| Dependencies | `Dependency` | name/version/scope/type (datastore\|broker\|service-binding\|http\|library), source (pom/gradle/VCAP), **engine** (postgres/kafka — folded in from DataStore, S1), **criticality** (critical-path?) | P2 |
| API + messaging contracts | `Interface` | style (rest\|grpc\|soap\|**async**); endpoints/channels{method/path or channel, handler, role, **idempotent?, retrySafe?**}; broker (Kafka/Rabbit/JMS), auth, deliveryGuarantee. **Ingests an existing OpenAPI/AsyncAPI doc if present (`common.openapi`, never generated) → `contract` drift**: documented vs undocumented (code-only) vs spec-only routes | P2 |
| Messaging consumer resilience | `Messaging` | consumers{channel, broker, handler, resilience{deadLetter, deadLetterMechanism, retry, idempotentConsumer}} — the consumer side `Interface` (contracts) doesn't cover. Tier-A from `@KafkaListener`/`@RabbitListener`/`@SqsListener`/`@JmsListener` + `@RetryableTopic`/`@DltHandler`/DLQ config; ordering/poison-pill/saga → Tier-B `map-messaging` | P2 |
| Jobs | `ScheduledJob` | trigger (cron/fixedDelay), expression, handler, **idempotent?, retrySafe?, dedupeKey** | P2 |
| Delivery | `DeliveryPipeline` | ci (Jenkins/GitLab/ADO), stages, artifactRepo, promotion, manifestRefs | P2 |
| Topology | `Topology` | nodes (service/store/broker/external), edges{protocol,dir}, pcfSpaces | P2 |
| Blast radius | `BlastRadius` | node (service/store/broker/dep), impactedFlows/services/SLOs (reverse-reachability), containment{resiliency/fallback refs}, coTenancy{sharedDB/broker/pcfSpace}, **stateful{dataLossRisk,RPO,RTO}**, **dependencyCriticality**, severityHint | **P1**(min) / P2(full) |
| Resiliency patterns | `ResiliencyPattern` | type (cb/retry/bulkhead/timeout/ratelimit), library, targetSymbol, config | **P1** |
| Logging + observability | `Observability` | **logging**{framework (logback/log4j2), format (json/pattern), patternString, correlationFields, levels}; metrics{name,type,meter}; tracing (Sleuth/OTel); healthIndicators; actuatorEndpoints | **P1**(logging) / P2(rest) |
| Feature flags | `FeatureFlag` | provider (config/spring-config/LaunchDarkly/Unleash/FF4J/Flagsmith), name, defaultState, killSwitch — detected from config blocks, `@ConditionalOnProperty`, and flag-SDK calls (`common.feature_flags`) | P2 |
| Built-in fallbacks | `Fallback` | trigger (exception/timeout/breaker-open), fallbackSymbol, behavior, forFlowStep | **P1** |
| Flows + failure points | `Flow` | trigger, steps{symbol,kind,failureModes[],**retrySafe?**}, sinks, **sloRef?** | **P1** |
| Alerts (proposed) | `Alert` | alertType (burn-rate\|threshold), sloRef?, signalSource (log-pattern/metric), expr (per backend), severity, forFlow, logFormatRef, rationale | **P1** |
| Runbooks | `Runbook` | trigger(alertRef), symptoms, diagnosis{step,evidenceRef}, remediation, escalation, relatedFlow | **P1** |
| SLO / SLI | `SloSli` | objectives{sli (latency/availability/error-rate), target, window}, source (code/config\|catalog\|needs-review), forFlow, errorBudget | **P1**(detect) / P2(full) |
| Data stores | ~~`DataStore`~~ → `Dependency` | **Folded into `Dependency` (S1)** — a datastore binding carries its `engine`; the infra fields (backup/restore, RPO/RTO) are platform-DR an app team doesn't own | — |
| Config management | `ConfigManagement` | sources (env/`application.yml`/Spring Cloud Config), `@RefreshScope`, profile matrix, **drives→** `FeatureFlag`/`Fallback` refs | P2 |
| Readiness + coverage | `ReadinessScore` | prrChecks{timeout-on-every-egress, healthcheck, SLO-defined, runbook-for-top-flows, structured-logging, …}, coverage{flowsWithAlerts %, flowGaps #, needsReview #}, score, gaps[] | **P1**(coverage) / P2(full PRR) |
| (Backstage projection) | `ServiceCatalogEntry` | type, lifecycle, system, providesApis, dependsOn | P1 |

**`SloSli` ties alerts to objectives:** when a flow has an SLO (detected from
Micrometer SLO/SLA buckets, timeouts, or an ingested SLO catalog), the generated
`Alert` is a **multi-window error-budget burn-rate** alert; with no SLO it falls back
to a threshold alert flagged `needs-review` so an SRE sets the objective. P1 does the
minimal detect-or-needs-review; P2 fills the full kind + error-budget math.

**Consolidations (fewer kinds, same coverage via sub-sections):** `Architecture`
absorbs design patterns · `Deployment` absorbs Infrastructure + capacity (incl. former
`HealthCheck`/`CapacityProfile`, all from the PCF manifest) · `Interface` unifies REST
+ messaging contracts · `Observability` unifies logging + metrics + traces + health.
That trims the catalog from 22 kinds to ~19 — less schema/collector/validator surface.

**Scope boundary — application team, not platform infrastructure (2026-06-09).** We own the
*application's* behavior and its contract with PCF (manifest, env vars, service bindings, routes,
health checks, scaling), **not** the platform beneath it. Kinds added to the schema after this catalog
that are platform-infra concerns should be pruned/folded: drop `NetworkTopology` and `DrBackup`; fold
`DataStore` → `Dependency` and `RateLimiting` → the resiliency signatures; trim `SecurityPosture` to
app-level controls. Two extraction gaps followed from the same scope and were **P0** — both now closed:
consumer-side **messaging resilience** (S3: the `Messaging` kind — DLQ / idempotent-consumer Tier-A,
poison-pill / ordering / saga Tier-B) and **logging format + quality** (S2: parsed statements + quality
on `Observability`, the prerequisite for log-based `Alert`s). See `SCOPE-AND-COVERAGE.md` (scope +
coverage contract) and HYBRID-PLAN §9.7 (S1–S5) for the full matrix and build order.

**New derived analyses & projections (reuse facts we already extract):**
- **`ReadinessScore` (kind)** — PRR checks + KB-coverage roll-up; P1 emits the coverage
  summary into `REVIEW.md`, P2 fills the full scorecard.
- **Timeout/retry-budget check (engine)** — deterministic finding when caller-timeout <
  callee-timeout, retry storms, or missing backoff; feeds `ReadinessScore` + can seed an
  `Alert`/`Runbook`. Lives in `flow/budget_check.py`. **P1**(minimal) / P2.
- **Diagrams (render projection)** — Mermaid **sequence diagram per `Flow`** (P1) +
  topology/blast-radius graph (P2), rendered into the KB/PR. `render/diagrams.py`.
- **Reliability guardrails (Copilot projection)** — generated `copilot-instructions`
  that make Copilot **preserve** circuit-breakers/timeouts/fallbacks/idempotency when
  editing, so the KB prevents reliability regressions, not just documents them. **P1**.

**Pruned to app-team scope (S1):** `NetworkTopology` (platform networking, incl.
ThousandEyes paths/ASGs), `RateLimiting` (already a resilience signature), and **`DrBackup`**
(platform DR/backup) were **removed**; `DataStore` **folded into `Dependency`** (`engine`). A
**`SecurityPosture`** collector (record secret *locations/types*, never values) remains a
future item — the kind is kept and app-scoped; the **redact pass + publish-time secret-scan gate**
that protect the PR are **built** — see *Secret safety* below.

Adding a kind = schema + prompt + (optional) collector + one `registry.yaml` row.

---

## Deterministic Python engine

- **Collector registry** keyed by `(language, framework)`; language detection
  (build files, extensions, manifest presence) selects a collector set, overridable
  by `config/profiles/*`. `Collector` protocol: `applies(ctx)` / `collect(ctx)→Iterable[Fact]`.
- **Normalized facts** (`models/facts.py`): `Fact{type, attrs, symbol, evidence}`
  streamed to `facts/facts.jsonl`. Provenance mandatory on every fact;
  `Symbol.fqn` is language-neutral (`com.acme.OrderController#createOrder`).
- **Code model** (`parsing/code_model.py`): a tree-sitter AST (Java + C#) is the
  structural backend for every code collector — per-class scoping, method/annotation
  spans, field name→type maps, real method invocations (receiver + line + string args),
  and try/catch. This replaced the line-regex extraction (which mis-scoped multi-class
  files and guessed correlation from call substrings).
- **Flow/call-graph** (`java_spring/flow_builder.py`): find entry points
  (`@RestController` handlers), resolve edges toward sinks (circuit-breaker target,
  Spring Data repo `save`, `KafkaTemplate`/producer) by walking the handler's actual
  invocations and **resolving each call's receiver to its field type** (so multiple
  publishers/clients are disambiguated), depth-limited. Unresolved hops become explicit `flow.gap` facts (surfaced, never
  faked). `failure_modes.py` annotates each edge with timeouts/retries/breakers and
  try-catch behavior (`surfacedAs: http-503` vs `logged-and-swallowed` +
  `dataLossRisk`) — the swallowed-failure detection is what seeds Alerts/Runbooks.
- **PCF** (`common/manifest_pcf.py`): parse `manifest*.yml`/vars →
  `pcf.app/route/service-binding/instance-limits` facts.
- **Spring config** (`config_props.py`): `application[-profile].yml`, Spring Cloud
  Config import/`bootstrap.yml`/`@RefreshScope`, Eureka, Actuator exposure,
  `resilience4j.*`/`management.metrics.*`. Each resolved key cites its defining line.

---

## The Copilot "skill/agent" driver (the default LLM transport)

**Agent Skills are the primary mechanism** (this is the "skill for VS Code" you
asked for); a custom agent orchestrates them; instructions + prompt files round it
out. Everything is LLM-neutral — skills pin no model; the agent leaves `model` unset
so the Copilot model picker (GPT / Claude / Gemini) decides. See *Verified
assumptions* at the end for the sourced facts behind every field below.

### Agent Skill = a self-contained, reference-rich folder

A skill is **a folder of instructions + references + scripts**, loaded by
*progressive disclosure*: L1 = `name`+`description` (always in context), L2 = the
`SKILL.md` body (loaded when the description matches the request), L3 = the
`references/`, `scripts/`, `templates/` (loaded only when the body links to them).
That progressive model is exactly why we put the heavy detail in **references** —
the skill stays cheap until needed, and the references are what "help the skill"
do high-quality, grounded work.

```
.github/skills/sre-flow-analysis/
├── SKILL.md            # frontmatter: name, description (WHAT/WHEN/KEYWORDS),
│                       #   allowed-tools (required house rule: declare the tool
│                       #   surface for least privilege), optional metadata{version}
│                       # body (<500 lines, imperative): the workflow + a Gotchas
│                       #   section, linking the references below
├── scripts/
│   └── run.sh          # thin wrapper → `sre-kb scan --run …` / `sre-kb validate`
├── references/         # the agent READS these to inform its synthesis
│   ├── envelope.md         # the metadata/evidence/confidence/status contract
│   ├── flow-schema.md      # the Flow kind: every field + what good looks like
│   ├── failure-modes.md    # catalog: timeout/retry/breaker-open/swallowed-write…
│   └── provenance-rules.md # "cite only path:line in context; never invent"
└── templates/
    └── flow.skeleton.yaml  # starter artifact the agent fills in & validates
```

Body links use **relative paths** (`See [Flow schema](./references/flow-schema.md)`
· `Run [the scanner](./scripts/run.sh)` · `Start from
[the skeleton](./templates/flow.skeleton.yaml)`). Skills are auto-discovered by
`description` or invoked directly via `/sre-flow-analysis`.

**The three P1 skills and the references each bundles** (references are the reusable
"help" the user wants baked in):

| Skill (`name`) | Purpose | Key `references/` |
|---|---|---|
| `sre-flow-analysis` | Build the request flow + failure points from facts | `flow-schema.md`, `failure-modes.md`, `envelope.md`, `provenance-rules.md` |
| `sre-alert-from-logs` | Derive alerts from log patterns + meters | `logging-format.md`, `alert-backends.md` (Splunk SPL · PromQL · AppDynamics health rules · Wavefront/Aria ts() · ThousandEyes path), `alert-schema.md`, `provenance-rules.md` |
| `sre-runbook` | Write a runbook from a flow + its alert | `runbook-schema.md`, `diagnosis-playbook.md` (which logs/endpoints/dashboards to check), `pcf-remediation.md` (restart/scale within instance limits, Spring Cloud Config flips), `provenance-rules.md` |

Shared references (`envelope.md`, `provenance-rules.md`) live once under
`skills/_shared/` and are symlinked/copied into each skill so the rules stay
identical. The canonical text is generated from the JSON Schemas + `prompts/` so a
schema change updates the references (no drift).

### Custom agent — the orchestrator

`.github/agents/sre-analyst.agent.md` (the renamed "chat mode"). Verified
frontmatter: `name`, `description` (required); `tools` (e.g.
`['codebase','search','editFiles','runCommands']` so it can run `sre-kb` and write
YAML); optional `handoffs`, `argument-hint`, `target`, `model` (**left unset** for
neutrality). Body = the SRE-analyst system prompt that drives the loop and hands
off to the `sre-*` skills. For enterprise reuse the same file can live in a
top-level `agents/` dir (no `.github/` prefix) so it is shared across repos.

### Instructions + prompt files

`.github/copilot-instructions.md` (and an `AGENTS.md`) carry always-on grounding —
the envelope and the "never invent provenance" rule. Per the verified precedence,
these layers **stack and merge** (personal → `copilot-instructions.md` →
`*.instructions.md`(`applyTo`) → `AGENTS.md` → skill → agent), higher wins only on a
direct conflict — so instructions, skills, and the agent reinforce rather than fight.
`.github/prompts/{flow,alert,runbook}.prompt.md` are thin one-shot entrypoints
reusing the same `prompts/<domain>/v1/template.md` text as the skill bodies.

### The loop (run by the engineer in VS Code)

`sre-kb scan` (engine — deterministic facts + scaffold) → the `sre-analyst` agent
invokes the `sre-*` skills (Copilot enriches: narrates flows, proposes
alerts/runbooks, cites code, reading the bundled references) → `sre-kb validate`
(engine; provenance/schema/crossref) → Copilot fixes flagged items →
`sre-kb render && sre-kb publish` (projection + PR). Because the skill's
`scripts/run.sh` bundles the `sre-kb` call, the agent self-corrects to green.

**Generated projections** (distinct from the authoring assets above) — written *per
analyzed service* into the SRE-repo PR so engineers consume the KB via Copilot: the
service's own `.github/skills/<skill>/`, `agents/sre-analyst.agent.md`,
`*.prompt.md`, and `copilot-instructions.md` — the latter including **reliability
guardrails** (e.g. "this egress must keep its circuit-breaker/timeout; this write is
non-idempotent — do not add blind retries") so Copilot *preserves* reliability when
editing. Plus **Mermaid sequence diagrams per flow** embedded in the runbooks. Each
stamped *"GENERATED from SRE KB — edit the KB, not this file."* Only `verified`
artifacts feed Copilot by default; generated consumer skills are instruction-only.

---

## Validation pipeline (layered; nothing silently dropped)

`structural` (jsonschema) → `provenance` (recompute `excerptHash` at the scanned commit,
and confirm the path resolves inside the repo root; mismatch/escape ⇒ downgrade) →
`crossref` (resolve `crossRefs`/inline refs; dangling ⇒ downgrade, **and** a verified
artifact that depends on a non-verified referent is downgraded to `needs-review`, iterated
to a fixpoint) → `gating` (config thresholds: `verified` needs `confidence ≥ 0.7` **and**
verified provenance; else routed to `kb/needs-review/`, never discarded) → an **adversarial
challenge** pass (deterministic grounding + an LLM hook; monotonic downgrade-only). A
`ValidationReport` (counts by status and trust tier, tier-conflicts, provenance failures,
dangling refs) becomes part of the PR body.

---

## Secret safety (baseline + active enforcement)

**Baseline holds by construction:** artifacts store `path:line` + an `excerptHash` (a
hash), **not raw code**, so secret *values* are never copied into the KB or PR — the design
avoids embedding source bytes in the first place.

**Active enforcement (built):** a **publish-time secret-scan gate** over the whole staged PR
tree **fails closed** on any match — a real secret is surfaced for human review, not silently
scrubbed — and it runs even on `--dry-run`, so the staged tree is always vetted before it can
be inspected or published. The explicit `--allow-secrets` override redacts (`redact_tree`)
regex-detectable secrets rather than publishing them raw. The ruleset spans private keys,
cloud/SaaS provider tokens, `Authorization`/URI credentials, and entropy/value-shape heuristics
(first-party schemas skipped), and the published repo carries a root-level CI workflow that
re-runs the gate. Still a
future item: a `SecurityPosture` collector that records secret *locations/types* (never
values) discovered in the target, masking any excerpt before render.

---

## Security & threat model

> **Status:** the output/publish hardening workstream below largely **landed in Phase 1**
> (HYBRID-PLAN §6); ✓ marks what is built. The no-credential scan role (read-only
> `sre-target-scan` agent) and a generated in-target CI gate have since landed; what remains is
> mostly process/infra (scoped publish role + CI wiring, supply-chain SHA-pinning).

**Trust boundary:** the **target repo is untrusted input**; our generated runbooks /
alerts / skills become **trusted operational guidance** (executed by on-call humans,
loaded by other engineers' Copilot). Poison in → trusted out, at incident time.

**Top risks → mitigations** (✓ = built):
- **Prompt injection** (repo comments/config steer Copilot into poisoned runbooks /
  skills / `copilot-instructions`) → ✓ untrusted-data framing in context packs (now a
  **non-escapable** fence) + ✓ dangerous-pattern output lint + ✓ sanitized renderers +
  mandatory human review / no auto-merge.
- **Engine RCE / DoS from a hostile repo** (unsafe YAML/XML, executing the target's
  build, symlink escape, ReDoS, zip-bomb) → ✓ safe parsers, ✓ **never run the target
  build**, ✓ no symlink-follow + file-size/resource budgets; sandbox (non-root, no-net)
  is a deployment concern.
- **SRE repo = aggregate weakness map + alert control** → access control + audit;
  no monitoring change auto-applied; ✓ the engine generates a **root-level CI gate** (KB
  validation + fail-closed `secret-scan`) + CODEOWNERS + PR template into the target, so its own
  CI treats the incoming KB as untrusted (needs the published engine to run).
- **Generated skills as a backdoor / RCE** → ✓ consumer skills instruction-only (no
  executable `scripts/`), least-privilege `tools`.
- **Untrusted-repo review without engine credentials** → ✓ read-only `sre-target-scan` agent
  (`codebase`/`search`/`usages` only — no write/run/network/publish), the no-credential half of
  the scan/publish split; route untrusted targets to it, not the command-capable analyst.
- **Secret / recon-data exfil via the PR** → ✓ fail-closed publish-time secret-scan gate
  (redaction on the `--allow-secrets` override; see *Secret safety*); document the Copilot
  enterprise data-boundary dependency.
- **Tool / prompt supply chain** → ✓ **sandboxed/autoescaped Jinja**; CODEOWNERS on
  `prompts/`+`schemas/` and pinned+hashed deps are infra (deferred).
- **False confidence → self-inflicted outage** → ✓ blast radius labeled "best-effort
  lower bound; `flow.gap`s may hide impact"; ✓ "GENERATED — verify before executing"
  banner + scanned-commit/age on every runbook.
- **Token blast radius** → ✓ publish confined to a repo **allowlist** + token kept out of
  `git` argv; least-privilege bot + short-lived/scoped tokens are infra (deferred).

**Free safe-defaults still used in Phase 0/1** (baseline correctness, *not* a hardening
feature): `yaml.safe_load`, no target-build execution, Jinja autoescape on, no
symlink-follow.

---

## Pipeline & CLI

Engine stages under `.work/<run-id>/`, resumable via `--from-stage/--to-stage`:
`clone → scan (facts + deterministic scaffold) → validate → review-gate → render → publish`.
**The engine embeds no model.** The synthesis / enrichment step sits *between* `scan`
and `validate` and runs through the configured `LLMProvider`: by default **Copilot in
VS Code** (the `sre-analyst` agent + `sre-*` skills) edits the scaffolded artifacts in
`candidates/` in place; `sre-kb worklist-run --oracle '<llm-cli>'` drives the same
scan-worklist tasks (discover + confirm + challenge) through a programmatic provider
end-to-end, writing the exact files the manual exchange would have. Either way every
output is re-grounded and gated. With no provider configured, CI / headless runs take
the **deterministic path only** (scaffold → validate → render) — exactly what the
offline e2e test exercises; `--from-stage validate` resumes after an enrichment
session.

```
sre-kb run     --target <path|git-url> [--profile java-spring-pcf] [--to-stage scan]
sre-kb scan    --run <id>            # deterministic facts + scaffold (no LLM)
sre-kb validate --run <id>           # schema + provenance + crossref + gating
sre-kb render  --run <id>            # Copilot projection + Backstage catalog
sre-kb publish --run <id> --sre-repo <git-url> --forge github [--dry-run]
sre-kb worklist-run --run <id> --oracle '<llm-cli>'   # run the whole LLM worklist programmatically
sre-kb validate-kb <dir>             # standalone validate an existing KB tree
sre-kb diff    --from <commit> --to <commit>   # P2: drift — diff the KB across commits
sre-kb schema list|show <kind>
```

`scan` and `validate` are exactly the commands the Copilot agent invokes from the
`sre-analyst` agent / `sre-*` skills — same CLI, human-run or agent-run.

**Drift detection (P2):** `sre-kb diff` re-scans a newer commit and diffs the KB
against the prior snapshot → a changelog (added/changed/removed artifacts, new
blast-radius/SLO findings, newly swallowed failures) and an **update PR**, so the KB
stays live instead of a one-time snapshot. The provenance `excerptHash` makes drift
exact: if a cited line moved or changed, the artifact is flagged automatically.

---

## Publish (SCM-neutral, GitHub first)

`Forge` protocol (`ensure_branch`/`put_files`/`open_pr`); the GitHub implementation
uses **git + the GitHub REST API** (token from env). The engine is a standalone tool,
so it does **not** depend on this session's `mcp__github__*` tools — those are only
available to the assistant in-session, not to the running engine. Per-service tree
written into the company SRE repo (Backstage-style, KB-as-data):

```
catalog/<service-id>/
  catalog-info.yaml                 # Backstage Component + relations
  kb/{verified,needs-review}/<kind>/<name>.yaml
  .github/{copilot-instructions.md, agents/sre-analyst.agent.md,
           skills/<skill>/SKILL.md, prompts/*.prompt.md}   # Copilot consumables
  REVIEW.md                         # validation summary + needs-review checklist
```

`--dry-run` writes the `pr/` tree without opening a PR (used by CI + the offline
e2e test). No PR is opened unless explicitly requested.

---

## Alerts & runbooks (grounded in code + your backends)

Both are *derived* kinds consuming `Flow` + `Observability` (logging sub-section in
P1; metrics/health in P2) + `ResiliencyPattern`/`Fallback`. They must cite the same
evidence, so ungrounded suggestions auto-downgrade to `needs-review`.

- **Alert** carries `signalSource` (log-pattern vs metric) and a backend-specific
  `expr` per target: **Splunk** SPL (matches the *real* logging format from
  `Observability`),
  **Prometheus** PromQL (only on meters that actually exist), **AppDynamics** health
  rule, **Wavefront / Aria Operations for Applications** ts() query, **ThousandEyes**
  for network/path-reachability signals. Seeds:
  swallowed failures / `dataLossRisk`, breaker-open, sink timeouts/error rates.
  **Objective-tied, not arbitrary:** if the flow has an `SloSli`, the Alert is a
  **multi-window error-budget burn-rate** alert against that objective; with no SLO
  it emits a threshold alert flagged `needs-review` so an SRE sets the objective.
- **Runbook** = `trigger:{alertRef}`, `symptoms` (from failure mode + exact log
  line), `diagnosis` steps each with an `evidenceRef` (which code/config/endpoint to
  inspect), `remediation` (PCF restart/scale **within instance limits** —
  `pcf.instance-limits` facts in P1, formalized in `Deployment` (capacity) in P2 —
  config flip via Spring Cloud Config, feature-flag toggle), `escalation` (`owner`).

Alert `severity` and Runbook depth/escalation are **ranked by `BlastRadius`** (below).

---

## Blast radius (`BlastRadius` — engine-computed, deterministic)

The engine builds the dependency/flow graph — in P1 from a single service's `Flow`
steps + PCF service bindings; in P2 extended with cross-service `Topology` +
`Dependency` edges — then for each node computes **reverse-reachability**:
the set of impacted flows, services, and SLOs if that node degrades. This is pure
graph math — deterministic, fully provenanced — so Copilot only *narrates* impact,
it never invents it.

- **Containment** reuses `ResiliencyPattern`/`Fallback` facts: a circuit-breaker /
  retry / fallback on the path *shrinks* the radius (degraded-but-up); a
  swallowed write with `dataLossRisk` *amplifies* it (silent data loss).
- **Co-tenancy (the PCF/on-prem payoff):** when multiple apps bind the same DB
  service, broker, or share a PCF org/space, a shared-resource failure's radius spans
  all tenants — detected from `pcf.service-binding` / shared-store facts. This is the
  on-prem risk cloud tooling routinely misses.
- **Stateful radius (datastore nodes):** for store nodes, the radius carries
  `dataLossRisk`, so a DB incident's impact is expressed as data loss, not just "down."
  (RPO/RTO/backup were platform-DR fields pruned with `DataStore` in S1 — the radius keeps the
  app-observable data-loss risk, not the infra recovery targets.)
- **Dependency criticality:** nodes on a critical path (no fallback, on a high-SLO
  flow) are flagged `dependencyCriticality: critical`, sharpening severity.
- **Drives prioritization:** `severityHint` feeds Alert `severity` and Runbook depth;
  high-blast nodes get the most thorough runbooks + explicit escalation. Runbook
  remediation also reads `retrySafe`/`idempotent` so it only suggests retry/replay
  where it is actually safe.
- **Scope:** P1 ships a **minimal, single-service** blast radius (which flows/steps
  fail if a given sink — e.g. `inventory-service` or `orders-postgres` — is down);
  P2 expands to **cross-service + shared-infra co-tenancy** once `Topology`/
  `Dependency` are populated across repos.

---

## Build order (historical)

The **P1/P2** markers in the kind catalog above record what shipped first, not open
work: **P1** was the Flow → Alert → Runbook vertical slice (collectors, the slice
kinds, the analyst agent + skills, the validation layers, render + `publish
--dry-run`); **P2** was the remaining kinds and sub-sections, full cross-service blast
radius, and drift detection. Both are built, as is most of the original P3/P4
hardening. The live roadmap and what remains are tracked in
[`HYBRID-PLAN.md`](HYBRID-PLAN.md) §8/§9.

---

## Verification

Everything below runs **offline in this container** (no Copilot, no network) via the
deterministic path; the fixture stands in for a cloned target repo:

1. `make test` → unit + golden + e2e green. The e2e runs
   `sre-kb run --target tests/fixtures/sample-spring-pcf --to-stage render` and
   snapshot-compares the emitted KB against `tests/golden/`.
2. `sre-kb validate-kb .work/<id>/kb` exits non-zero if any artifact fails schema or
   provenance — proving the validation gate works.
3. Inspect `.work/<id>/kb/verified/Flow/*.yaml` for real `path:line` evidence into
   the fixture; confirm the generated `Alert` + `Runbook` cite the same lines and the
   alert `expr` is present for each selected backend.
4. `sre-kb publish --dry-run` produces the `catalog/<service>/…` tree + PR body;
   verify the Backstage `catalog-info.yaml` and the `skills/` projection.
5. **Copilot loop (manual, in the user's VS Code):** open the run dir, switch to the
   `sre-analyst` custom agent and invoke the `sre-flow/alert/runbook` Agent Skills
   (or `/sre-flow-analysis`), let the agent run `sre-kb scan/validate` and enrich
   until validation is green.

## Assumptions / defaults (correct me if wrong)

- Collectors ship for Java/Spring on PCF, .NET/Steeltoe, Python/FastAPI, Node/Express,
  and Go; a new stack is a new collector set in the registry, not a redesign.
- Target repo is **cloned locally** by the engine (or an existing local path passed
  in); arbitrary outbound clone may be limited by the environment's network policy,
  so the fixture is the primary offline proof.
- Copilot agent/skill/prompt frontmatter **pins no model** (LLM-neutral); Agent
  Skills + custom agents (`.agent.md`) are the mechanisms — not the retired
  `.chatmode.md`.
- No real PR is opened during the slice — `--dry-run` only — unless you ask.

---

## Verified assumptions (re-checked June 2026, with sources)

Re-checked because the first draft had a stale mechanism (chat modes). ✅ = verified
and reflected above; ⚠️ = corrected from the first draft.

| Claim driving the design | Status | Source |
|---|---|---|
| "Chat modes" renamed to **custom agents** (`.agent.md` in `.github/agents/`; frontmatter `name`/`description`/`tools`/`model`/`handoffs`/`argument-hint`/`target`); org-level top-level `agents/` for reuse | ⚠️→✅ | [VS Code custom agents](https://code.visualstudio.com/docs/agent-customization/custom-agents) · [GitHub custom-agents config](https://docs.github.com/en/copilot/reference/custom-agents-configuration) |
| **Agent Skills** are a first-class feature (GA **2025-12-18**): folder `.github/skills/<name>/SKILL.md`; frontmatter `name`+`description` required, `license`/`allowed-tools`/`metadata` optional; subdirs `scripts/`,`references/`,`templates/`,`assets/`; relative-path links; **progressive disclosure** (name/desc → body → resources); body **<500 lines** | ✅ (new) | [Changelog 2025-12-18](https://github.blog/changelog/2025-12-18-github-copilot-now-supports-agent-skills/) · [About agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) · [awesome-copilot](https://github.com/github/awesome-copilot) |
| Skills invoked by **description auto-match** or `/skill-name`; install many, only ~1–3 expand per task | ✅ | [VS Code Agent Skills](https://code.visualstudio.com/docs/agent-customization/agent-skills) |
| Instruction layers **stack/merge**: personal → `copilot-instructions.md` → `*.instructions.md` (`applyTo`) → `AGENTS.md` → skill → agent; higher wins only on direct conflict; AGENTS.md + copilot-instructions both apply | ✅ | [VS Code custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions) |
| **AsyncAPI** current = **3.1.0 (Jan 31 2026)** — first draft's "2.6" was stale | ⚠️→✅ | [AsyncAPI releases](https://github.com/asyncapi/spec/releases) |
| **OpenAPI** current = **3.2.0 (Sep 2025)**; 3.1 aligns with JSON Schema 2020-12 (what our schemas use) — ingest 3.0–3.2 | ⚠️→✅ | [OpenAPI spec](https://spec.openapis.org/oas/) |
| **Wavefront** → Tanzu Observability → now **VMware Aria Operations for Applications** (Broadcom); query lang = ts()/WQL | ⚠️→✅ | [Broadcom TechDocs](https://techdocs.broadcom.com/us/en/ca-enterprise-software/it-operations-management/vmware-aria-operations-for-applications/saas.html) |

**Assumed stable (within knowledge cutoff; will re-validate against the fixture
during build, not taken on faith):** Backstage `catalog-info.yaml` (`kind:
Component`) shape; Spring Boot Actuator / Micrometer / Resilience4j-Hystrix
semantics; PCF `manifest.yml` keys; JSON Schema **2020-12** via the `jsonschema`
lib; and alert-query syntaxes for **Splunk SPL**, **PromQL**, **AppDynamics** health
rules, and **ThousandEyes** path/alert rules. If any of these has shifted, the
`alert-backends.md` / `pcf-remediation.md` references are the single place to fix —
they are data, not code.
