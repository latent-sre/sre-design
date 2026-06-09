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
> - `docs/DEEP-COMPARISON-2026-06-07.md` / `-06-09.md` — point-in-time comparisons vs. `resiliency-skills`.
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
| 7 | API contracts | `Interface` | A/B | ◐ | deterministic endpoints; OpenAPI/AsyncAPI ingest + versioning gaps → skill |
| 8 | **Messaging** | *(no kind)* | A/B | ❌ | **biggest gap**: contracts partly in `Interface`, but **no consumer resilience** — DLQ, poison-pill, ordering, idempotent-consumer |
| 9 | Jobs | `ScheduledJob` | A | ✅ | idempotent?/dedupeKey fields exist |
| 10 | Delivery | `DeliveryPipeline` | A | ◐ | CI/CD discovery |
| 11 | Topology (app→deps) | `Topology` | A | ✅ | app-centric, not platform |
| 12 | Resiliency patterns used | `ResiliencyPattern` | A | ✅✅ | flagship; 10 signatures |
| 13 | Logging | `Observability` | A/B | ◐ | presence yes; **quality** (req/trace IDs, levels → alert fatigue) is a gap |
| 14 | Observability | `Observability` | A/B | ✅ | metrics/traces/health + coverage skill |
| 15 | Feature flags | `FeatureFlag` (S) | A | ❌(S) | schema exists, **no detector** |
| 16 | Built-in fallbacks | `Fallback` | A | ✅ | |
| 17 | Flows + where a request can fail | `Flow` + `BlastRadius` | A | ✅✅ | flagship |
| 18 | **Logging format (parse the statements)** | *(new, feeds #19)* | A | ❌ | **prerequisite for log-based alerts**; currently shallow |
| 19 | Create alerts from code + logging | `Alert` (render) | A+B | ◐ | renders 6 backends; needs #18 to be accurate |
| 20 | Create runbooks from deep scan | `Runbook` (render) | A+B | ◐ | renders; content drafting → skill |
| R | **SRE rubric** (timeouts, retries+backoff, swallowing, unbounded loops/queues, no-pagination, conn-pooling, leaks, migration safety, config-vs-code, idempotency, async DLQ/poison/ordering, load-shed, saga) | `ResiliencyGap` + above | A/B | ◐ | strong on *absence-of-mechanism* (timeouts/swallowing/fallback); weak on *anti-pattern* detection (resource/op-safety) and semantic (saga/ordering) |

## 5. Kinds to prune or fold (follows from §2)

These carry schema + render + validation weight for concerns an application team does not own:

| Kind | Action | Why |
|---|---|---|
| `NetworkTopology` | **Drop** | platform networking |
| `DrBackup` | **Drop** | platform DR/backup (keep only app-data the app controls) |
| `DataStore` | **Fold into `Dependency`** | we care "app binds Postgres," not the DB as infra |
| `RateLimiting` | **Fold into resiliency** | already a signature; app-level only |
| `SecurityPosture` | **Trim** | keep app controls (authz/secret handling), drop infra security |

Pruning is the concrete answer to "are we over-engineering?": *yes, on infra-shaped kinds we don't
own* — not on the core extract→metadata→populate loop, which is well-proportioned.

## 6. The LLM gate — discover + confirm, as skills

The engine **never calls a model** (`docs/DESIGN.md`); the LLM is Copilot, driven by **skills**, and is
a **pointer-generator, not a fact source** (`.github/skills/sre-gap-finder/SKILL.md` is the contract
model). The gate has two loops:

- **Discover (recall)** — a skill proposes byte-anchored gaps the engine missed. *Exists today* for
  resiliency; widen the taxonomy to all Tier-B areas (§7).
- **Confirm (precision) — NEW** — after a rerun, the engine hands a skill its own present/absent
  boundary calls; the skill disputes/affirms them **with anchors**, and the engine re-grounds at the
  cited bytes. Catches false-positive gaps (a real timeout the regex missed) and false-negative
  "present" claims (a mechanism that's present but disabled/misconfigured). Recurring confirms feed
  `graduation` → Tier-A.

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

Existing: `sre-criticality`, `sre-flow-analysis`, `sre-estate`, `sre-gap-finder`,
`sre-observability-coverage`, `sre-blast-radius`, `sre-prr-review`, `sre-security-posture`,
`sre-generate-slos`, `sre-generate-dashboards`, `sre-incident-response`.

New (each pointer-generator, discover+confirm, read-only on targets; add to `.github/skills/pipeline.yaml`):

| Skill | Covers | Priority |
|---|---|---|
| `map-messaging` | #8 consumer resilience: DLQ, poison-pill, ordering, idempotent-consumer | **P0** |
| `assess-logging` | #13 + #18: log *format* parse + quality (req/trace IDs, levels) — unblocks #19 | **P0** |
| `map-api-contracts` | #7: OpenAPI/AsyncAPI ingest, undocumented endpoints, versioning | P1 |
| `map-architecture` | #2 + #3: architecture narrative, design patterns | P1 |
| `generate-alerts` | #19: draft alert *intent* from code+logs (engine renders dialect) | P1 |
| `generate-runbooks` | #20: draft runbook content from deep scan | P1 |

## 8. Build order (priorities)

1. **Close the two P0 extraction gaps:** `map-messaging` (consumer resilience) and `assess-logging`
   (format + quality). These are the highest-value holes for an app team on PCF, and #18 gates #19.
2. **Graduate idempotency-on-mutating-route to Tier-A.** The pieces exist (HTTP verb in endpoints +
   `idempotency` signature); make "POST/PUT or consumer handler with no idempotency guard in scope"
   a deterministic gap. Cheap, verifiable, high value.
3. **Build the confirm loop** (§6) — start with absence-claims (false-positive gaps erode reviewer
   trust fastest at stage 1).
4. **Stand up the eval harness** (§9) so accuracy is a number, not a vibe — the gate to stage 2.
5. **Then** drafting skills (`generate-alerts`/`-runbooks`) and the prune (§5).
6. Defer publish/agent surfaces until accuracy clears the bar.

## 9. How accuracy is measured (the rubric is the spec)

The §4 matrix + the SRE rubric **are** the coverage contract. Turn them into an eval harness:

- Run the engine over labeled `tests/fixtures/sample-*` repos.
- Compute **precision/recall/coverage per area and per detector** (generalize the existing
  `copilot-gap-validate` precision/recall from gaps-only to all extraction).
- Report a scorecard; **precision will be structurally lower for Tier-B/semantic rows — that's
  expected, not a bug.** Stage 2 is unlocked when the rows you intend to trust clear their bar.

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

These should be folded into HYBRID-PLAN's §9.7 backlog and DESIGN.md's kind catalog rather than living
only here.
