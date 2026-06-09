# Scope & coverage: what we extract, how, and where the gaps are

Date: 2026-06-09

> **What this doc is.** A product-scope + extraction-coverage spec for an **application team**. It is
> the lens that turns "extract patterns from a repo to populate SRE needs" into a concrete, testable
> coverage contract. It does **not** restate the architecture or the plan — those live in:
>
> - `docs/DESIGN.md` — the architecture (deterministic Python engine + Copilot-as-only-LLM, the
>   `apiVersion/kind` artifact backbone, the three neutralities, PCF reality). Still authoritative.
> - `docs/HYBRID-PLAN.md` — the implementation plan + **live status** (§8 tracker, §9 reassessment,
>   §9.7 backlog). Still the single source of truth for status.
> - `docs/DEEP-COMPARISON-2026-06-09.md` — point-in-time comparison vs. `resiliency-skills`.
>
> This doc adds three things those don't yet state explicitly: a **scope boundary** (app team, not
> platform-infra), a **coverage matrix** (every focus area → Tier-A collector vs Tier-B skill → status
> → priority), and a **prune list** that follows from the boundary. The deltas vs. the existing docs
> are listed at the end.

## 1. Mission, in one sentence

Read an application repo (and its PCF deployment) and produce a validated, evidence-grounded SRE
knowledge base that a human reviews now, that drafts alerts/runbooks/docs once it's accurate, and that
eventually grounds an incident agent — **for code and config the application team owns.**

## 2. Scope boundary (the decisive constraint)

**We are an application team. We do not own platform infrastructure.** We care about *how the
application behaves and is configured*, including its contract with PCF — not the platform beneath it.

| In scope | Out of scope |
|---|---|
| Application code behavior (flows, resiliency, failure modes, idempotency, messaging, jobs) | Platform networking, the PCF foundation, load balancers, the mesh |
| The app's PCF descriptor: `manifest.yml`, env vars, service bindings (VCAP), routes, health checks, instances/memory/disk, buildpack | Platform DR, datacenter/VM provisioning, cluster ops |
| App-level observability: what the code emits (logs/metrics/traces), log *format* and *quality* | Collector/agent infrastructure, telemetry backends' own health |
| App-level resilience: timeouts, retries, breakers, fallbacks, rate-limit/load-shed *in the app* | Gateway/edge rate limiting, infra firewalls |
| App data safety the app controls (outbox, idempotency, DLQ wiring it declares) | Database/broker infrastructure DR and backup |

This boundary is what makes the over-engineering judgment concrete (see §5): several artifact kinds are
platform-infra concerns we don't own.

## 3. The maturity curve (why accuracy gates everything)

1. **Now — human-reviewed.** A human reads the KB to fine-tune extraction and find gaps; the LLM
   confirms. Output is advisory.
2. **Next — trusted drafting.** Once extraction is *measurably* accurate: auto-draft runbooks, keep
   docs current, discover new services.
3. **Later — agent grounding.** Feed an incident agent ("what's the blast radius, what should I
   check") — the KB is the static map; live signals are a separate join.

Each stage is gated on the previous. The gate for stage 2 is **measured accuracy** — which is why the
coverage matrix below doubles as the eval scorecard (§8).

## 4. Coverage matrix — focus areas × detection

Detection sits on a difficulty gradient that decides which tier an item belongs in:

- **Syntactic** (one file, regex/AST) and **cross-reference** (join facts across collectors) →
  **Tier-A** deterministic, can reach `verified`.
- **Flow/semantic** (intent, multi-step/multi-service dataflow) → **Tier-B** LLM, always `needs-review`.

Status legend: ✅ solid · ◐ partial · ❌ gap · (S) schema/kind exists but no detector.

| # | Focus area | Kind / output | Tier | Status | Notes / gap |
|---|---|---|---|---|---|
| 1 | Tech stack (detailed) | `TechStack` | A | ✅ | build files + buildpack |
| 2 | Detailed architecture | `Architecture` | B | ◐ | narrative is LLM judgment |
| 3 | Design patterns used | `Architecture` (or new) | B | ❌ | no detector; semantic |
| 4 | Infrastructure (= app's PCF descriptor) | `Deployment` + `pcf.app`/`pcf.service` | A | ✅ | env/bindings/routes/health/scale extracted |
| 5 | Deployment | `Deployment` | A | ✅ | PCF manifest |
| 6 | Dependencies | `Dependency` | A | ✅ | |
| 7 | API contracts | `Interface` | A/B | ✅ | deterministic endpoints **+ OpenAPI/AsyncAPI ingest + contract drift** (`common.openapi`: documented vs undocumented vs spec-only) **+ baseline-spec breaking-change diff + semver version-policy** (Tier-A, byte-grounded vs `.sre/api-baseline/`); **semantic-break judgment** via `map-api-contracts` (Tier-B, re-grounded by `pipeline.contract`) |
| 8 | **Messaging** | `Messaging` + `Interface` | A/B | ✅ | S3: `Messaging` kind + `java_spring.messaging` consumer-resilience (DLQ/retry/idempotent-consumer, Tier-A) + Tier-A gaps; ordering/poison-pill/saga → Tier-B `map-messaging` |
| 9 | Jobs | `ScheduledJob` | A | ✅ | idempotent?/dedupeKey fields exist |
| 10 | Delivery | `DeliveryPipeline` | A | ◐ | CI/CD discovery |
| 11 | Topology (app→deps) | `Topology` | A | ✅ | app-centric, not platform |
| 12 | Resiliency patterns used | `ResiliencyPattern` | A | ✅✅ | flagship; 10 signatures |
| 13 | Logging | `Observability` | A/B | ✅ | S2: statements parsed (level dist, parameterization); deterministic **quality** (req/trace-ID correlation context, alert-fatigue signals) + Tier-B `sre-assess-logging` judgment |
| 14 | Observability | `Observability` | A/B | ✅ | metrics/traces/health + coverage skill |
| 15 | Feature flags | `FeatureFlag` | A | ✅ | `common.feature_flags`: config blocks + `@ConditionalOnProperty` + flag-SDK calls (LaunchDarkly/Unleash/FF4J) |
| 16 | Built-in fallbacks | `Fallback` | A | ✅ | |
| 17 | Flows + where a request can fail | `Flow` + `BlastRadius` | A | ✅✅ | flagship |
| 18 | **Logging format (parse the statements)** | `Observability` (feeds #19) | A | ✅ | S2: `java_spring.log_statements` parses framework/level/parameterization from the AST — the log-based-alert prerequisite |
| 19 | Create alerts from code + logging | `Alert` (render) | A+B | ✅ | renders 6 backends; deterministic burn-rate + swallowed-publish log alerts (Tier-A) **+ `generate-alerts` Tier-B drafter** — error/warn log lines a human reviews, grounded against #18's log-statement facts |
| 20 | Create runbooks from deep scan | `Runbook` (render) | A+B | ✅ | deterministic swallowed-publish runbook (Tier-A) **+ `generate-runbooks` Tier-B drafter** — diagnosis/remediation content for an uncovered Alert, grounded closed-world against the run's artifacts |
| R | **SRE rubric** (timeouts, retries+backoff, swallowing, unbounded loops/queues, no-pagination, conn-pooling, leaks, migration safety, config-vs-code, idempotency, async DLQ/poison/ordering, load-shed, saga) | `ResiliencyGap` + above | A/B | ◐ | strong on *absence-of-mechanism* (timeouts/swallowing/fallback); weak on *anti-pattern* detection (resource/op-safety) and semantic (saga/ordering) |

## 5. Kinds to prune or fold (follows from §2) — ✅ done (S1)

These carried schema + render + validation weight for concerns an application team does not own:

| Kind | Action | Status | Why |
|---|---|---|---|
| `NetworkTopology` | **Drop** | ✅ removed | platform networking |
| `DrBackup` | **Drop** | ✅ removed | platform DR/backup (keep only app-data the app controls) |
| `DataStore` | **Fold into `Dependency`** | ✅ folded (`Dependency.engine`) | we care "app binds Postgres," not the DB as infra |
| `RateLimiting` | **Fold into resiliency** | ✅ removed | already a signature; app-level only |
| `SecurityPosture` | **Trim** | ✅ kept as-is | schema is already app-scoped (authn/authz/secrets); no infra fields to drop |

Pruning is the concrete answer to "are we over-engineering?": *yes, on infra-shaped kinds we don't
own* — not on the core extract→metadata→populate loop, which is well-proportioned. **Done in S1:** 4
schemas + 4 golden examples + their registry rows removed; `DataStore.engine` folded onto `Dependency`.

## 6. The LLM gate — discover + confirm, as skills

The engine **never calls a model** (`docs/DESIGN.md`); the LLM is Copilot, driven by **skills**, and is
a **pointer-generator, not a fact source** (`.github/skills/sre-gap-finder/SKILL.md` is the contract
model). The gate has two loops:

- **Discover (recall)** — a skill proposes byte-anchored gaps the engine missed. *Exists today* for
  resiliency; widen the taxonomy to all Tier-B areas (§7).
- **Confirm (precision) — ✅ done (S4, both directions)** — the engine hands a skill its own boundary
  calls (`confirm/boundary-calls.json`); the skill affirms or disputes **with anchors**, and the engine
  re-grounds at the cited bytes (`pipeline/confirm.py`, `sre-confirm-boundaries` skill, `confirm-apply`).
  Two directions, both byte-re-derived by the engine: an **absence** dispute can only *drop* a
  false-positive gap (point at real code where the engine's signature fires in scope); a **presence**
  dispute (the false-negative "present-but-disabled" direction) can only *add* a byte-proven Tier-A
  `disabled-resilience` gap — the engine offers each active mechanism (a named circuit breaker), and a
  dispute confirms only when a deterministic `enabled: false` disable signal fires for that instance.
  **Graduation-from-confirms ✅ done:** `confirm-apply` now feeds its verdicts into the same graduation
  tally `confirm-gap` drives — a confirmed disable accrues toward graduating a *proactive* Tier-A
  disable collector (the natural promotion of this category), a refuted absence records a false positive
  that blocks graduation and flags an over-firing probe.

```
run 1: engine emits {present, absent} with evidence
       skill (discover) → new anchored proposals;  skill (confirm) → dispute/affirm boundary calls
run 2: engine RE-GROUNDS proposals + disputes at cited bytes → recall ↑, false positives ↓
       repeated zero-FP confirmations → graduation → deterministic Tier-A
```

**Invariant:** a skill never asserts a verdict the engine trusts. The skill points; the engine judges;
graduation promotes. This is what keeps the loop non-circular.

### Skills, not collectors, for the Tier-B half only

A skill exists **only** for areas needing LLM judgment. Deterministic areas stay engine collectors —
a skill re-deriving ground truth is redundant and a precision hazard. Each Tier-B skill carries **both
discover and confirm modes** (confirm judgment is domain-specific). On an untrusted target, skills are
**read-only** (`allowed-tools: [codebase, search]`, never `editFiles` — the R4 target-scan role).

## 7. Skills to author (maps onto the resiliency-skills catalog, per DEEP-COMPARISON R6/R7)

Existing: `sre-criticality`, `sre-flow-analysis`, `sre-estate`, `map-messaging`, `sre-gap-finder`,
`sre-observability-coverage`, `sre-assess-logging`, `sre-blast-radius`, `sre-prr-review`,
`sre-security-posture`, `sre-generate-slos`, `sre-generate-dashboards`, `sre-incident-response`.

New (each pointer-generator, discover+confirm, read-only on targets; add to `.github/skills/pipeline.yaml`):

| Skill | Covers | Priority |
|---|---|---|
| ~~`map-messaging`~~ ✅ | #8 consumer resilience: DLQ + idempotent-consumer (Tier-A); ordering/poison-pill/saga (Tier-B) | **done** |
| ~~`assess-logging`~~ ✅ | #13 + #18: log *format* parse (Tier-A) + quality judgment (Tier-B) — unblocks #19 | **done** |
| ~~`map-api-contracts`~~ ✅ | #7: ~~OpenAPI/AsyncAPI ingest, undocumented endpoints~~ ✅ (deterministic, `common.openapi`); ~~**versioning/breaking-change** judgment~~ ✅ — baseline-spec diff + version-policy are Tier-A (`common.openapi`), the semantic-break half is the `map-api-contracts` skill re-grounded by `pipeline.contract` | **done** |
| `map-architecture` | #2 + #3: architecture narrative, design patterns | P1 |
| ~~`generate-alerts`~~ ✅ | #19: draft which error/warn log lines warrant an alert (alert-fatigue judgment); the engine grounds the line against its log-statement facts, refutes info/debug by level, generates the query, and drafts a needs-review log-pattern Alert (`pipeline.alerts_draft`, `sre-kb generate-alerts`) | **done** |
| ~~`generate-runbooks`~~ ✅ | #20: draft diagnosis/remediation content for an uncovered Alert; the engine grounds the trigger Alert and every Kind/name citation closed-world against the run (`pipeline.runbooks_draft`, `sre-kb generate-runbooks`) | **done** |

## 8. Build order (priorities)

1. **Close the two P0 extraction gaps:** ~~`map-messaging` (consumer resilience)~~ ✅ and
   ~~`assess-logging` (format + quality)~~ ✅. **Both done** (S2 + S3): logging statements parsed with
   the quality assessment, and consumer-side messaging resilience (DLQ/idempotency Tier-A;
   ordering/poison-pill/saga Tier-B). The two highest-value app-team holes on PCF are closed.
2. ~~**Graduate idempotency-on-mutating-route to Tier-A.**~~ ✅ **Done (S4 quick win):**
   `collectors/common/idempotency.py` emits a deterministic Tier-A `missing-idempotency` gap for every
   mutating route with no idempotency guard in scope.
3. ~~**Build the confirm loop** (§6)~~ ✅ **Done (S4, absence-claims):** `pipeline/confirm.py` +
   `sre-confirm-boundaries` + `confirm-apply` re-ground a skill's disputes of the engine's absence
   claims, dropping false positives. Started with absence-claims as planned.
4. **Stand up the eval harness** (§9) so accuracy is a number, not a vibe — the gate to stage 2. **(S5,
   next.)**
5. ~~**Then** drafting skills — `generate-alerts` (log-pattern drafter, grounded on the #18
   log-statement facts) and `generate-runbooks` (closed-world grounded on the run's artifacts).~~ ✅
   **Both done**; the prune (§5) is done.
6. Defer publish/agent surfaces until accuracy clears the bar.

## 9. How accuracy is measured (the rubric is the spec)

The §4 matrix + the SRE rubric **are** the coverage contract. **The eval harness exists** (S5,
`eval/scorecard.py`, CLI `sre-kb eval`):

- Run the engine over labeled `tests/fixtures/sample-*` repos (`<fixture>/.sre/eval-truth.json` —
  expected artifacts by kind+name, expected detectors).
- It computes **precision/recall per area (kind) and coverage per detector** (generalizing the
  `copilot-gap-validate` precision/recall from gaps-only to all extraction). Precision is scoped to
  labeled kinds, so partial labeling doesn't penalize an unlabeled-but-correct artifact.
- It reports a scorecard; **precision will be structurally lower for Tier-B/semantic rows — that's
  expected, not a bug** (the per-area `verified` count surfaces the Tier-A/Tier-B split). Stage 2 is
  unlocked when the rows you intend to trust clear their bar. **Twelve fixtures are labeled and score
  1.0/1.0**, spanning both AST stacks and the polyglot endpoint collectors: `sample-spring-pcf`,
  `sample-messaging`, `sample-dotnet-steeltoe` (.NET/Steeltoe), `sample-multiflow` and `sample-billing-pcf`
  (Java), `sample-jobs` (#9), `sample-feature-flags` (#15), `sample-logging` (#13/#18), `sample-api`
  (#7 contracts), and the polyglot `sample-fastapi` / `sample-node-express` / `sample-go-gin` (Python /
  Node / Go endpoint + tech-stack detection). A CI guard (`test_every_labeled_fixture_scores_clean`,
  parametrized over every labeled fixture) re-scores each on every run, so a regression that drops or
  fabricates an artifact in a scored area fails the build. Label more fixtures to widen it further.

### The measurement recipe (today, gap-finder; generalize to all Tier-B)

The Tier-B half already has a working, reproducible measurement loop — `copilot-gap-validate`. It is
the seed of the harness above; the same shape extends to every discover/confirm skill. The engine
**never calls a model**, so the model boundary is an explicit manual step:

1. `sre-kb run --target <service> --to-stage scaffold` — produces a fresh context pack.
2. In VS Code, run Copilot with the relevant `SKILL.md` and save the answer to
   `<service>/.sre/gap-proposals.json` (the discover output; a `confirm` exchange file is the
   confirm-loop analogue, §6).
3. Write a target truth file, e.g.
   `{"expected": [{"category": "missing-timeout", "target": "payments-api"}],
   "controls": [{"category": "missing-timeout", "target": "shipping-api"}]}`.
4. Measure: `sre-kb copilot-gap-validate --target <service> --truth <service>/.sre/gap-truth.json
   --report .work/gap-validation.json`.

The report separates **raw proposal quality** from **post-grounding quality**: proposal
recall/precision, kept recall/precision, grounded rate, missed-expected, proposed controls, and
false-positive survivors. Archive the proposals + truth + report together so a claim is reproducible.
(First real-Copilot sample run: `sample-gap-finder` measured 4/4 proposed/grounded/kept/confirmed,
recall and precision `1.00`, zero false-positive survivors — see HYBRID-PLAN §9.5. Service-scale noise
remains open.)

## 10. Deltas vs. the existing docs (what this conversation actually changed)

DESIGN.md and HYBRID-PLAN.md already encode most of this (app-team, PCF, Copilot-only-LLM, the kinds,
messaging *contracts*, idempotency fields, the gap-finder taxonomy, the skill pipeline + graduation).
This conversation added:

1. An **explicit scope boundary** (§2) and the resulting **prune list** (§5) — DESIGN.md implies PCF
   focus but doesn't say "drop infra kinds."
2. **Logging-format extraction** (#18) as a first-class, P0 need and a *prerequisite* for log-based
   alerts — not previously called out.
3. **Consumer-side async resilience** (DLQ/poison/ordering) as a P0 gap — messaging was covered as
   *contracts*, not consumer *resilience*; saga/distributed-txn noted as permanently Tier-B.
4. The **confirm loop** (§6) — the docs have discover (gap-finder) but not the LLM reviewing the
   engine's boundary calls.
5. The **rubric-as-spec / eval-harness** framing (§9) and the **over-engineering verdict** as a prune,
   not just additive backlog.

These are now folded into the authoritative docs: **HYBRID-PLAN §9.7 (S1–S5)** as open backlog items,
and **DESIGN.md**'s kind catalog as the scope-boundary + prune note. This doc remains the detailed
coverage matrix + eval recipe they reference.
