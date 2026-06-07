# Round-3 deep review — `sre-design` ↔ `resiliency-skills` (2026-06-07)

A fresh three-pass competitive re-review of **both repos at their current `main`**, commissioned
because "the plans are getting stale." Method mirrors the prior rounds: read/run from source, verify
every claim at `file:line` or by executing, three depth passes under all three lenses
(SDE → SRE → architect).

> **Relationship to existing docs.** [`REASSESSMENT-2026-06.md`](REASSESSMENT-2026-06.md) is a
> historical snapshot (Rounds 1–2); [`HYBRID-PLAN.md`](HYBRID-PLAN.md) §8/§9 is the live tracker.
> This doc is **Round 3**: it re-validates that the live tracker matches reality *and* surfaces the
> lift candidates §8/§9 do **not** yet cover. Where it recommends plan changes they are called out in
> §7 for folding into HYBRID-PLAN.

**Pinned commits.** `sre-design` @ `8a7b4c4` (`origin/main`, PR #23). `resiliency-skills` @ `f99e028`
(`origin/main`, PR #15 — confirmed the latest `main` by push timestamp; their newer activity is on
unmerged branches). Both built and tested in this review: **`sre-design` 235 passed**, **`latent-sre`
engine 69 passed** (the last audit, §9.6, never ran theirs — now closed).

---

## 1. Verdict (TL;DR)

1. **The plan is not stale — it is current and accurate.** Every HYBRID-PLAN §8/§9 "✅" was
   re-confirmed against code at `8a7b4c4`; the suite is green (235). The prior §9.6 competitive audit
   was taken at the *same* `f99e028` that is still their `main`, so the comparison was not out of date
   either. The "staleness" worry is unfounded **on the axes the plan already tracks.**
2. **But the fresh pass found four lift candidates the plan does *not* track** — all from
   `resiliency-skills`' "reliability model" (their Batch D) and `assemble` internals that §9.6
   explicitly skipped ("their reliability model batch was not deep-read; their engine tests didn't
   run"). These are the real yield of this round (§4).
3. **The strategic frame is unchanged and re-confirmed: one-directional lift, no merge.** Their
   `docs/roadmap.md` (PR6) commits to *orchestration + breadth + supply-chain scale*, with **zero**
   move toward AST/byte-grounding. Divergence holds; our grounding moat is intact and now broader (27
   kinds, Java/.NET/Python, gap-finder wired into `run`).
4. **Tier-B skill expansion is warranted — but only when each new skill is paired with a
   deterministic probe.** Adding ungrounded judgment skills just grows the `needs-review` pile.
   Adding a skill that feeds a *deterministic* consumer (the new severity floor) or carries a
   refutation/confirmation probe is on-thesis (§5). Noted per the request: it works **conditionally**.

---

## 2. What is actually current (the anti-staleness check)

Our `main` advanced materially *today* (PRs #15–#23), and the docs kept pace:

| Capability | Status @ `8a7b4c4` | Evidence |
|---|---|---|
| AlertIntent model on our envelope | ✅ | PR #16; `Alert.schema.json`; `render/alerts.py` |
| Render-adapter seam + 4 backends (prom/splunk/wavefront/appd) | ✅ | `render/alerts.py:194` `_BURN_ADAPTERS` |
| `Dashboard` + `ScheduledJob` kinds adopted (byte-grounded) | ✅ | PR #19; `schemas/v1alpha1/` |
| Substance gate (schema-valid-but-empty can't stay verified) | ✅ | PR #18; `validation/substance.py` |
| Python/FastAPI collector (repo-neutrality) | ✅ | PR #17; `collectors/python_fastapi/` |
| Gap-finder wired into `run`; refute/confirm/judgment split | ✅ | `collectors/llm/gap_finder.py:58-79` |
| Two false-refute holes closed (fallback signature, whole-token scope) | ✅ | PR #23/`f19f2d0`; `gap_finder.py:203-209` |

**Open in the plan already (still open):** grafana + thousandeyes adapters (§9.6 #2); supply-chain
`--require-hashes` + Renovate digest-pin (§9.6 #3 / §9.3 #5); full scan/publish credential split
(§9.3 #5). These are tracked; this round only re-affirms them.

`resiliency-skills` @ `f99e028` is unchanged on the structural axes: **8 signatures** (5 framework +
3 messaging; `lib/signatures/`), **18 skills** (`.github/skills/`), **6 alert adapters**
(`engine/templates/adapters/`), still **not byte-grounded** (provenance is a required
`repo/commit/scanDate/skill` block; no line/excerptHash). A new `lib/taxonomy.yaml` centralizes their
controlled vocabulary ("fat config") — confirming, not contradicting, the divergence thesis.

---

## 3. Three-pass review

### Pass 1 — SDE lens (code, correctness, maintainability)

- **Both green, both clean.** 235 / 69 passing. Their engine is small and well-factored (`assemble.py`
  is a single readable orchestration; `render.py` a tight adapter dispatcher). Ours is larger and
  deeper (27 kinds, 5-layer validation, real AST), and the gap-finder
  (`collectors/llm/gap_finder.py`) is genuinely sophisticated: a three-way probe split
  (refute / confirm-and-graduate / judgment-route) with an honest `checked:` trail and a noise budget.
- **Their `signal.query` passthrough is still an SDE smell** (`render.py:84` → adapter `query`): an
  LLM-supplied query string renders verbatim into a deliverable rule. Our adapters *deterministically
  generate* the query from a typed intent (`render/alerts.py`). **Implication for any lift: take their
  adapter *template structure*, never their passthrough.** (This is how we already lifted the other 4.)
- **Their `_effective_severity` (`render.py:32-38`) is exemplary deterministic code** — a tier→severity
  floor that can only *raise* severity, never lower an author's declared value, with a rank table and
  a clean monotone rule. Directly portable as an *idea* (§4.1).
- **Their `assemble` clobber-merge (`assemble.py:165-199`) is well-engineered**: a `.sre/manifest.yaml`
  of content hashes drives a 3-way merge — unchanged files refresh, human-edited files route to
  `.proposed/` (never clobbered), orphaned AI outputs are pruned, path collisions fail closed. Our
  publish path (`publish/pr_builder.py:63-65`) does `rmtree` + recreate — simpler, but with **no
  re-scan idempotency against operator edits** (§4.3).

### Pass 2 — SRE lens (operability, trust, paging discipline)

- **Severity floored by criticality tier is the single best SRE idea we don't have.** Paging severity
  on a tier-0 service must not depend on an LLM's `severity` guess; their floor makes it deterministic
  (`TIER_SEVERITY_FLOOR = {tier0: sev1, tier1: sev2, …}`). We emit alerts deterministically but let
  severity ride author/LLM intent with **no criticality anchor** (`render/alerts.py` has no tier
  input; grep confirms no `Criticality`/severity-floor on our side). This is a precision-vs-recall-free
  win that *strengthens* the fat-engine thesis (§4.1).
- **`dataClassification` (pii/pci) is missing on our side and is core SRE governance** — it drives
  blast-radius weighting, runbook handling ("this path touches PII"), and alert routing. Their
  `Criticality` schema carries `tier` + `businessCriticality` + `dataClassification[]` +
  `source: catalog|human-input|inferred`. The `source` enum is the tell: criticality is usually *not*
  in code, so it is honestly sourced from a catalog or human — which maps cleanly onto our trust model
  (§4.2).
- **Re-scan safety.** An SRE running this monthly against a live `SRE-<service>` repo must not have
  their hand-tuned runbook/CODEOWNERS reverted. Their manifest guarantees it; our PR model *surfaces*
  the revert as a reviewable diff but still **proposes** it (noise, and a real regression risk if
  auto-merge is ever enabled) (§4.3).
- **Backend parity for the monitoring stack.** They render 6 (incl. grafana + thousandeyes/synthetic);
  we render 4. Synthetic checks (thousandeyes) are a distinct SLI class an SRE wants (§4.4 / already
  §9.6 #2).
- **Where we are ahead (SRE):** the substance gate (empty artifacts can't stay verified — they have no
  analogue), byte-grounded evidence a reviewer can one-click verify, and the monotonic challenge loop
  that *caught a wrong-signal latency alert* their model rendered straight through.

### Pass 3 — Architect lens (boundaries, strategy, divergence)

- **Divergence re-confirmed at source.** `docs/roadmap.md` PR6 is "orchestration & scale"
  (`latent-sre plan` over a `pipeline.yaml` of all 18 skills, fan-out, resumable `--scan-state`) —
  breadth and operability, not grounding. No roadmap item adds AST or `file:line`. **The hybrid stays
  a one-way absorption; do not merge repos.**
- **The Criticality kind is an *input-layer* gap, not just a feature.** It is the deterministic anchor
  the whole reliability model hangs off (severity floor, blast radius, data-handling). Lifting it —
  adapted to our grounding (`source: inferred` carries Tier-A PII/PCI signatures; `source: catalog`
  reads a repo-local `catalog-info.yaml`/`.sre/criticality.yaml`; otherwise Tier-B/judgment) — slots
  *under* our existing scoring (`scoring/risk.py`, `scoring/readiness.py`) and makes them
  criticality-aware. On-thesis.
- **Their orchestration (`plan` + resumable scan-state) is a scale capability we partially lack.** We
  have `estate` (cross-service topology) and a fan-out cap, but no resumable multi-service plan. Minor;
  note for later, not this round.
- **Tier-B skill expansion must respect the non-circular contract** (HYBRID-PLAN §6.3). A new skill is
  on-thesis **iff** its output is either (a) re-derivable by a deterministic probe, or (b) consumed by
  a deterministic engine step, or (c) an honest judgment routed to the oracle *with a recall eval*.
  Skills that only emit ungrounded judgment widen the `needs-review` pile without raising trust — the
  exact failure mode we built the contract to avoid (§5).

---

## 4. New lift candidates (not in the current plan)

Classified **lift** (port adapted) vs **refactor** (rework ours), with effort/risk.

### 4.1 Deterministic **severity floor by Criticality tier** — *lift the idea, build grounded* — **[HIGH]**

Their `render.py:32-38`. A service's tier sets a severity **floor** the author can exceed but not
undercut. For us: thread the service `Criticality.tier` into `render/alerts.py` and floor
`Alert.spec.severity` deterministically; emit the floor application as engine-derived (Tier-A) so it
is hash-grounded to the criticality source. **Effort:** S–M (one intent field + a monotone rule + a
test). **Risk:** low. **Depends on 4.2** for the tier input.

### 4.2 **`Criticality` kind** (tier / businessCriticality / dataClassification) — *lift, adapted to our grounding* — **[HIGH]**

Their `criticality.schema.json`. Adopt onto our envelope with our status/evidence/confidence model
(not their `needs-human-review: const`). Three honest sources:
- `source: catalog` → read a repo-local `catalog-info.yaml` / `.sre/criticality.yaml` (Tier-A,
  byte-grounded to that file).
- `source: inferred` → **Tier-A `dataClassification` signatures** (PII/PCI field & annotation
  patterns: `@Email`, `ssn`, `cardNumber`, PAN regexes) — deterministic and groundable.
- `source: human-input` / tier when undeclared → Tier-B/`needs-review` (no fabrication).

Feeds 4.1, and makes `scoring/risk.py` / blast-radius criticality-aware. **Effort:** M. **Risk:** low.

### 4.3 Engine-owned **clobber-protection manifest** on publish — *refactor ours* — **[MED-HIGH]**

Their `assemble.py:165-199`. Add a `.sre/manifest.yaml` of content hashes to our publish path so a
re-scan: refreshes unchanged generated files, routes operator-edited files to `.proposed/` instead of
reverting them, prunes orphans, and fails closed on output-path collisions. Our PR model softens the
blast radius but does not eliminate the revert-proposal. **Effort:** M. **Risk:** low–med (touches
`publish/pr_builder.py`; additive). High operational payoff for repeat runs.

### 4.4 **"Pattern without load-bearing params is itself a gap"** — *new Tier-A recall* — **[MED]**

Their `assess-resiliency` SKILL.md:31-34 + structured `gaps[]` (`resiliency.schema.json:34-47`). The
insight is **deterministic and belongs in Tier-A**: a `retry` with no `backoff`/`budget` (retry-storm
risk), a `timeout` with no `timeoutMs`, a `circuit-breaker` with no `thresholds` are mis-parameterized
gaps the engine can assert from facts it *already extracts*. This raises recall **without** the LLM and
feeds the §7.9 graduation loop (it is exactly the kind of rule a confirmed Tier-B category graduates
into). **Effort:** S–M. **Risk:** low. Distinct from our current taxonomy, which is presence/absence,
not parameter-completeness.

### 4.5 (Already tracked) grafana + thousandeyes adapters; supply-chain hardening

§9.6 #2/#3 — re-affirmed, unchanged. Take template structure for grafana/thousandeyes and feed our
deterministic query; lift their `--require-hashes` lockfile + Renovate digest-pin verbatim.

---

## 5. Tier-B skills — the explicit ask, assessed honestly

**Does adding more Tier-B skills work? Conditionally — yes, and here is the rule.** A Tier-B skill
earns its place only if it honors the non-circular contract. Mapping the candidates against it:

| Candidate (source skill) | Output | Groundable? | Verdict |
|---|---|---|---|
| **assess-criticality-and-data** | `Criticality` (tier, dataClassification) | **Yes** — Tier-A PII/PCI signatures + catalog read (4.2) | **Add (highest value)** — feeds the deterministic severity floor |
| **assess-observability-coverage** | observability gaps | **Partial** — refute against our `Observability` facts (metric/health present?) | **Add with a refutation probe** |
| map-messaging gaps | DLQ/idempotency on a broker hop | Partial — confirm against messaging facts | Add later (we have `undocumented-job` precedent) |
| data-loss-path / unbounded-resource (focused skills) | judgment only | **No probe** | **Hold** — only with a recall-eval fixture, else pure noise |

So the recommendation is **not** "add 16 more skills to match their 18." It is: add the **two**
contract-respecting ones (criticality-and-data → severity floor; observability-coverage → refutation
probe), each with its deterministic probe and a recall-eval fixture (the dual of the adversarial
corpus, per §7.9). That genuinely raises recall; a blanket skill dump would not.

> **Note per the request ("note if it works or does not"):** Tier-B skill expansion *works* when each
> skill is anchored to a deterministic probe or consumer — it then compounds via the graduation loop.
> It *does not work* (it dilutes trust) when added as free-floating judgment. The
> criticality-and-data skill is the clean case that works; it doubles as the input to 4.1/4.2.

---

## 6. Recommendations (prioritized)

| # | Action | Type | Lens | Effort | Risk | Value |
|---|---|---|---|---|---|---|
| R1 | `Criticality` kind (catalog + Tier-A PII/PCI signatures) | lift→grounded | SRE/arch | M | low | **HIGH** |
| R2 | Deterministic severity floor by tier in `render/alerts.py` | lift idea | SRE | S–M | low | **HIGH** |
| R3 | `assess-criticality-and-data` Tier-B skill feeding R1 | new skill | arch | S | low | **HIGH** |
| R4 | Clobber-protection manifest on publish | refactor | SRE/SDE | M | low–med | MED-HIGH |
| R5 | Tier-A "pattern-without-params" resiliency gaps | new Tier-A | SRE | S–M | low | MED |
| R6 | observability-coverage Tier-B skill + refutation probe | new skill | SRE | M | low | MED |
| R7 | grafana + thousandeyes adapters (template only) | lift | SRE | S–M | low | MED |
| R8 | Supply-chain `--require-hashes` + Renovate digest-pin | lift | SDE | S | low | MED |

**Sequencing.** R1→R2→R3 is one coherent vertical slice (the *criticality reliability spine*) and is
the highest-leverage, most on-thesis work — it also satisfies the Tier-B-skills ask cleanly. R4/R5 are
independent SRE hardening. R7/R8 are low-risk parallel lifts already half-tracked.

> **Status (2026-06-07): R1–R3 + R5 landed.** The criticality reliability spine is implemented and
> tested (`Criticality` kind + `common.criticality` collector; deterministic `effective_severity`
> floor, grounded-tier-only; the Tier-B `sre-criticality` skill + `.sre/criticality-proposal.yaml`
> path). R5 added the Tier-A parameter-completeness gaps (`circuit-breaker-without-thresholds`,
> `retry-without-backoff`) via `collectors/java_spring/resiliency_params.py`, routed through the same
> `scaffold_gap` gate. 253 green, lint clean. Tracked in HYBRID-PLAN §8. R4 (clobber manifest),
> R7 (grafana/thousandeyes), R8 (supply-chain) remain open; R5's timeout-duration completeness is
> deferred (a `@TimeLimiter` has a library default; Tier-B `missing-timeout` covers timeout absence).

---

## 7. Plan deltas (fold into HYBRID-PLAN.md)

The live tracker is accurate but blind to the reliability model. Proposed edits when work begins:

- **New §10 (or §8 "Adopted kind — `Criticality`")** for R1–R3: the criticality reliability spine,
  with the deterministic severity floor as its first consumer.
- **§9.3 add item:** clobber-protection manifest on publish (R4) — currently no line covers re-scan
  idempotency.
- **§7.9 taxonomy add:** parameter-completeness gaps as a **Tier-A** category (R5), explicitly the
  deterministic dual of the Tier-B absence gaps.
- **§9.6 lift actions:** keep #2 (grafana/thousandeyes) and #3 (supply-chain); add the criticality
  schema lift as #4.

**Bottom line.** The plan isn't stale — but the reliability model behind `resiliency-skills`' breadth
(severity floor + criticality + structured gaps) is the one substantive thing we hadn't mined, and it
maps onto our grounded thesis better than it fits theirs. The criticality spine (R1–R3) is the
recommendation.
