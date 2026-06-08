# sre-design ↔ resiliency-skills: deep comparison, findings, and a hybrid plan

A source-level comparison of this repo (`sre-design` / the `sre-kb` engine) with
[`latent-sre/resiliency-skills`](https://github.com/latent-sre/resiliency-skills)
(the `latent-sre` engine + Copilot skill suite), the concrete weaknesses found in each,
and a phased plan to combine their strengths.

> **Provenance of this doc.** Both repos were read end-to-end from source (this one locally;
> `resiliency-skills` from a fresh clone of `main`). Every load-bearing claim below was
> verified at a named file/line or by executing the code — not taken from a README. Where a
> finding turned out to encode *tested intent* rather than a bug, that is called out.

> **Status authority (consolidated 2026-06-07).** This doc is the **single source of truth** for the
> plan + live status: **§8** is the implementation-status tracker, **§9** the rolling reassessment
> (incl. **§9.7**, the open backlog). The only other docs are `DESIGN.md` (architecture) and
> `PHASE-4-GAP-FINDER.md` (the gap-finder spike). The separate review/reassessment snapshots
> (Rounds 1–3 + the parallel competitive review) were **folded in here and retired** — their
> reasoning remains in git history. **When anything disagrees with §8, §8 wins.**

---

## 1. The headline: fat engine vs. fat skills — and a shared lineage

Both repos are from `latent-sre` and target the same goal: turn a service repo into a
populated, validated SRE knowledge base / `SRE-<service>` repo (Backstage catalog, runbooks,
SLOs, alerts, architecture). They make **opposite architectural bets** about who extracts the
facts.

| | **this repo** (`sre-design` / `sre-kb`) | **`resiliency-skills`** (`latent-sre`) |
|---|---|---|
| Philosophy | Deterministic **fat engine**, thin LLM | "**Thin skills, fat config**, deterministic transforms" |
| Who extracts the facts? | The **engine**, via tree-sitter **AST** parsing | **Copilot**, via 18 granular LLM skills |
| Role of the LLM | A *passenger* in a deterministic harness: enriches engine-scaffolded artifacts, adjudicates judgment calls | The *driver*: scans / maps / assesses / generates the artifacts |
| LLM harness strength | **Mechanical** — citations are hash-checked; challenge is downgrade-only | **Advisory** — skills say "don't fabricate", only schema-shape + human enforce it |
| # of Copilot skills | 1 (`sre-flow-analysis`) + agent + prompts | 18 (`assess-*`, `generate-*`, `map-*`, `publish-*`) |
| Languages today | Java/Spring + .NET/Steeltoe (real AST collectors) | Any (LLM), backed by **8** detection signatures |

### These read as two phases of one evolution, not two rivals

`docs/DESIGN.md` (`§Security & threat model`, lines ~407-439) lists, as *deferred / "Phase TBD"*
work: untrusted-data framing, dangerous-pattern lint, mandatory human review, sandboxed Jinja,
a least-privilege token scoped to PRs-only, CODEOWNERS on prompts/schemas, and pinned+hashed
deps. **That list is, almost item-for-item, `resiliency-skills`' *implemented* security
posture.** The most useful way to read the two repos:

- **`sre-design`** = the deep, deterministic **extraction core**, with security hardening
  consciously *documented and deferred*.
- **`resiliency-skills`** = the **hardened, broadened productization** that executed exactly
  that deferred roadmap — but, going skill-first for breadth, **dropped the deterministic
  byte-grounding** that is `sre-design`'s crown jewel.

So the hybrid is not "merge competitors"; it is **reunite the two halves the same lineage
split apart.**

---

## 2. Two theories of trust

Read end to end, **both systems quietly rely on the human as the real correctness gate.**
`resiliency-skills` says so openly (`needs-human-review: true` is a schema `const`); `sre-design`
implies it (everything non-trivial downgrades to `needs-review`; its LLM challenge oracle is a
hook that isn't wired live yet). Neither's automated gates *decide* "is this claim true."

What differs is how they make that human review viable:

- **`sre-design` = verifiability.** Every claim carries `path:line` + a recomputed `excerptHash`,
  so a reviewer can check it in one click. *Gives the reviewer the tools to check.*
- **`resiliency-skills` = containment + a hard human gate.** The scan agent has no terminal /
  network / write credential, so a wrong or hostile artifact can't escalate while it waits.
  *Gives the reviewer the mandate, and makes review safe.*

`resiliency-skills` has the safe gate with **nothing to check against** (its artifacts carry no
file:line evidence). `sre-design` has **checkable evidence with a breakable gate** (a textual
injection fence, see §4). That gap is the entire argument for the hybrid.

---

## 3. What each does that the other can't

**`sre-design` is the more trustworthy *analysis*:**
- Real, tested **AST extraction** (`parsing/code_model.py`) — per-class scoping, field-type→receiver
  correlation, try/catch swallow detection. 95→101 tests.
- **Byte-grounded provenance** (`collectors/base.py:hash_excerpt` + `validation/provenance.py`):
  proves the cited bytes exist verbatim. (It does *not* prove the claim is true — see honest
  docstring at `provenance.py:4-10`.)
- A **sound 5-layer pipeline** wired in correct order; challenge gating is genuinely monotonic
  downgrade-only with an audit trail (`pipeline/orchestrator.py`, `validation/challenge.py:207-217`).
- **Reliability guardrails** (`render/copilot.py`) — a genuinely unique forward feature: the KB
  is projected back into the developer's Copilot as rules ("don't remove `@CircuitBreaker`",
  "don't swallow this exception — add an outbox") so future edits don't regress reliability.
  `resiliency-skills` has no analogue.
- Substantive differentiating features: `findings` (ranked risk digest), `drift` (semantic diff
  that flags data-loss regressions), `estate` (cross-service co-tenancy detection).

**`resiliency-skills` is the more defensible *system*:**
- **Architectural injection containment**, *tested* with `examples/malicious/{AGENTS.md,README.md,manifest.yml}`:
  the scan agent holds no credential, `needs-human-review` is `const: true`, names are sanitized.
- **Safe-by-construction renderers** — `render.py` (sandboxed Jinja + `tojson`/`sanitize`),
  `dashboard.py` (dict→`json.dumps`), `runbook.py` — all tested with hostile payloads.
- **Fail-closed `redact`** secret gate + an independent second gate (`tools/second_secret_gate.py`
  wrapping `detect-secrets`); fan-out cap (`appnames.py:FANOUT_CAP=20`); supply-chain pinning;
  self-defending generated repo (vendored schemas, least-privilege CI, CODEOWNERS sentinel).

But its **breadth is thinner than it looks**: the "18 skills / fat config" are `SKILL.md`
stubs + Copilot reasoning, backed by only **8 deterministic signatures** (`lib/signatures/`:
5 frameworks, 3 messaging systems, 0 datastores/infra/observability). It defines 17 artifact
*shapes* comprehensively; the *detection* behind them is LLM reasoning, not implemented detectors.

---

## 4. Verified findings

### `sre-design` — bugs found (fixed on this branch)

These were verified at the source and **fixed with regression tests** in the same change as this doc:

1. **Swallow false-positive** (`parsing/code_model.py`): `"log" in (recv+meth)` flagged
   `catalog`/`backlog`/`dialog` receivers in a catch block as logged-and-swallowed, seeding a
   spurious data-loss claim — which then propagated into a wrong *reliability guardrail* in the
   developer's editor. **Fixed:** match log-level method names / logger-shaped receivers; also
   now inspects every catch clause, not just the first (a logged-swallow in a later catch was
   previously missed).
2. **Ungrounded attribution in the deterministic path** (`collectors/java_spring/flow_builder.py`):
   `_match_pub`/`_match_repo` fell back to the *first* publisher/repo when a receiver's type was
   unresolved, fabricating a wrong-but-confident sink. **Fixed:** fall back only to a *sole*
   unambiguous candidate; never guess among several. (The sole-candidate fallback is intended
   and tested.)
3. **`findings.py` didn't understand `"critical"`** (`reporting/findings.py`): `_SEV_RANK` had
   no `critical` entry, so a co-tenancy `severityHint: critical` finding sorted to rank 9 (below
   `info`) and wasn't counted in the high/medium tally — the most severe findings were
   effectively hidden. **Fixed:** `critical` ranks above `high` and counts as high-or-above.
4. **Mermaid output not sanitized** (`render/diagrams.py`): untrusted strings (service name and
   REST path from annotations, resource/binding names from `manifest.yml`) were interpolated raw
   into Mermaid labels/messages/relations — a render-integrity / diagram-spoofing gap.
   `resiliency-skills` hardened exactly this. **Fixed:** sanitize the metacharacters that could
   break out of a label or inject diagram syntax (node ids were already sanitized).

### `sre-design` — weaknesses noted (now closed in Phase 1/2; see §8)

These were the gaps the hybrid set out to fix; all are implemented in code as of 2026-06-07:

- **Injection fence** (`synth/context_pack.py`) — fence/sentinel runs in cited excerpts *and*
  paths are now defanged, so a hostile source file can't close the `<<<UNTRUSTED …>>>` block
  early. *(Was: textual and breakable.)*
- **Publish path** (`publish/forge/github.py`) — the token is kept out of `git` argv
  (env-injected auth) and live publishes are confined to a `publish.allowed_repos` allowlist
  (empty = block-all). *(Was: token in argv, no allowlist.)*
- **Status-aware gates** (`validation/crossref.py`, `scoring/readiness.py`) — a verified
  artifact citing a non-verified referent is downgraded to a fixpoint; artifact-presence
  readiness credits only verified coverage. *(Was: name-only resolution, status-blind grade.)*
- **Provenance path-confinement** (`validation/provenance.py`) — evidence paths must resolve
  inside the repo root (`is_relative_to`); `../`/absolute escapes are rejected. *(Was: none.)*

### Findings that turned out to be *tested intent*, not bugs (calibration)

- `scoring/risk.py`: the `"low"` severity branch is **unreachable**, but `test_risk.py:21-23`
  asserts a contained single-flow dependency is `medium` — the design **deliberately floors a
  tracked dependency at medium**. Dead code, not wrong output; left as-is. (The real bug nearby
  was the `findings.py` `"critical"` handling, fixed above.)
- `estate/topology.py` hard-codes `severityHint: "critical"` for co-tenancy, which `test_estate.py:44`
  asserts. Defensible for a shared datastore with data loss; the genuine downstream bug was that
  `findings.py` mis-ranked that `critical`, now fixed.

### `resiliency-skills` — weaknesses

- **No file:line evidence in any artifact.** Provenance is `repo/commit/scanDate/skill`; even the
  optional `source.path` is unenforced and `RunbookSpec` has no source field. The human-review
  gate has nothing to verify against — the structural epistemic gap.
- **Schemas are permissive on substance** — `Resiliency` passes with empty `patterns`+`gaps`;
  `RunbookSpec` requires only `title`. Structure is gated; truth is not.
- **Breadth is thin** (8 signatures); coverage rides on Copilot reasoning quality.
- Minor/unverified: `renovate.json` action-pinning claim (T7) couldn't be confirmed from the
  repo; the "redact + detect-secrets are complementary" claim has no rule matrix.

### Confirmed strengths (both)

- `sre-design`'s **pipeline plumbing is correct** (5 layers in order; challenge monotonic;
  audit trail). The weaknesses are gate *strength*, not wiring.
- `resiliency-skills`' **output layer is safe-by-construction and hostile-payload-tested**;
  6/8 threats in `docs/security.md` are code-backed, 2 are honest deployment preconditions.

---

## 5. Bottom line

- **Most trustworthy *analysis* today: `sre-design`.** Only it verifies a claim against source
  bytes, and only it has real, tested extraction.
- **Most defensible *system* today: `resiliency-skills`.** If you had to point one at a hostile
  repo tomorrow, it's this one.
- **Neither is production-trustworthy alone.** `sre-design` would leak/spoof through unsanitized
  output and a breakable fence; `resiliency-skills` would emit confident, unverifiable claims a
  human can't efficiently check.

Pick by estate if forced to ship one as-is: **mostly Java/.NET and correctness-critical →
`sre-design`; polyglot and breadth-first → `resiliency-skills`.** Otherwise, build the hybrid.

---

## 6. The hybrid plan

**Thesis:** keep `resiliency-skills`' implemented hardening *and* skill-driven breadth, but fence
the LLM output behind `sre-design`'s byte-level grounding + sound validation pipeline. This is
mostly *adding a second kind of collector*, because the repo already pivots on the right seam: a
language-neutral `Fact` with provenance (`models/facts.py`) that collectors emit and the
scaffolder consumes. AST collectors and LLM skills can both produce `Fact`s; everything
downstream (scaffold → validate → render → publish) is unchanged.

### Trust tiers

Ride a trust tier on the existing `Evidence.detector` provenance:

- **Tier A — AST collectors** (existing): deterministic, high-trust. Java/.NET today.
- **Tier B — LLM skill collectors** (new, from `resiliency-skills`): broad-stack, lower-trust,
  **cannot reach `verified`** until grounded.

A router picks Tier A where a tree-sitter grammar exists, Tier B otherwise. On overlap, **AST
wins**; Tier B only fills gaps AST can't reach.

### The non-circular Tier-B contract (the crux)

The naïve "LLM emits `path:line`, engine recomputes the hash" is **circular** — if the same model
produces both the claim and the cited excerpt, the hash only proves the excerpt is real, and a
substring grounding check only proves the model quoted its own keyword (exactly the self-consistency
trap `validation/challenge.py:9-13` warns about). Instead:

1. Treat the LLM as a **pointer/hypothesis generator**, not a fact source. It proposes a claim +
   the excerpt *text* (not a line number — LLMs are unreliable at exact lines); the engine
   *locates* the bytes and stamps `path:line:hash` itself.
2. The engine **independently re-derives** the fact at that location with the *same deterministic
   rule Tier A uses* (AST/regex confirms the breaker annotation is actually there). The LLM only
   widened coverage; the assertion is deterministic.
3. Where no deterministic confirmation exists (judgment calls — runbook-step safety, alert
   appropriateness), route to a **separate** LLM adjudication context (finally wire
   `LLMChallenger`'s oracle) — never self-grade.

### Phases (reordered by everything the deep review found)

| Phase | What | Why first/last |
|---|---|---|
| **0. Fact contract & trust tiers** ✅ | Add `source_tier: ast\|llm` to `Fact`/`Evidence`; a `CollectorProtocol` both tiers satisfy. No behavior change. | Foundation. |
| **1. Adopt `resiliency-skills`' hardening wholesale** ✅ | Architectural scan/publish split (no-credential scan role; scoped publish credential), sandboxed/`json.dumps` renderers, `redact` + second gate, fan-out cap, `needs-human-review` const. | This *is* `sre-design`'s own deferred roadmap. Closes the textual-fence and publish-path weaknesses **before** any LLM breadth is added. |
| **2. Make the trust spine status-aware** ✅ | Fix `crossref`/`readiness`/gating to require `verified` referents; confine provenance paths (`is_relative_to`). | Or Tier-B facts will silently inflate "verified" graphs. |
| **3. Challenge loop (Copilot oracle)** ✅ | Judgment-call claims → worklist; Copilot adjudicates; `challenge-apply` re-gates monotonically. In-process `LLMChallenger` superseded by the worklist (engine stays model-free). | Prerequisite for Tier-B — deterministic grounding is circular for LLM judgment claims. |
| **4. LLM collectors: gap-finders + pointer-generators** 🟡 (gap-finder spike) | `collectors/llm/`. The LLM reads the engine's facts + the cited code and proposes **(a) gaps the engine missed on code we already cover** (the recall payoff — §7.9) and **(b) pointers for stacks no AST grammar reaches** (breadth). The engine re-derives or *refutes* each (§6.3, §7.9); nothing verifies on proposal alone. | Recall on covered estates **and** breadth, both safely fenced. |
| **5. Render-adapter breadth** 🟡 | Generalize `render/` to neutral-intent → adapter; add Wavefront/AppDynamics. | Independent; can run in parallel. *(Seam + 4 alert backends landed; see §8.)* |

Phases 0→1→2 are the trust/security spine and are low-risk extensions of existing code; they land
first. Phase 4 was the only heavy lift and the only new LLM-integration risk — and the spike has
since cleared that bar (§9). The remaining order has been revised post-spike from "expand Phase 4,
then Phase 5" to **integrate before expand**; see **§9.3** for the current sequence.

### Lift verbatim from `resiliency-skills`

Ownership/credential boundary (`docs/ownership-boundary.md`); safe renderers (sandboxed Jinja,
dict→`json.dumps`); `redact` + second secret gate; fan-out cap + name sanitization; self-defending
generated repo; supply-chain pinning; `render-adapters` multi-tool breadth.

### Keep from `sre-design`

Byte-level provenance (`hash_excerpt`) + the monotonic challenge pipeline; the AST extraction core;
the `Flow`/`Topology`/`estate`/`BlastRadius` graph depth; `findings` + `drift`; and the unique
**reliability guardrails** that feed the KB back into the developer's editing loop.

---

## 7. Enhancements (second-pass review)

> **Provenance of this section.** A second pass over §6 after re-reading both repos. These do **not**
> change the spine or the phase order — they harden the Tier-B contract and exploit two assets §6
> under-uses: the `drift`/`findings` graph and the reliability guardrails. Each is tagged by value
> and slotted into the existing phases.

### 7.1 Tier-B as a cross-check on Tier-A, not only a gap-filler — **[HIGH]**

§6 rules "on overlap, AST wins; Tier-B only fills gaps." But **all four bugs in §4 were in
Tier-A** — "AST wins" discards a free signal. Instead, on overlap, **compare**: when a Tier-B
claim *disagrees* with a Tier-A fact (the LLM asserts a circuit breaker where the AST found none,
or misses one the AST has), emit a `tier-conflict` finding rather than silently dropping Tier-B.
This is a near-zero-cost detector for Tier-A extraction bugs — it would have surfaced the swallow
false-positive (§4.1) before it reached a guardrail. *Wiring:* both tiers already become `Fact`s;
route the overlap through `validation/crossref.py` and add a conflict rule in
`reporting/findings.py`. *Slots into:* finding type in **Phase 2**; activates in **Phase 4**.

### 7.2 Tier-aware reliability guardrails — **[HIGH]**

`render/copilot.py` projects findings back into the developer's editor as hard rules ("don't remove
`@CircuitBreaker`", "add an outbox"). §4.1 shows the failure mode: a false finding becomes a *wrong
guardrail* the developer is told to obey. Enhancement: **only Tier-A (byte-grounded) findings emit
hard guardrails; Tier-B findings emit advisory notes.** The blast radius of an LLM mistake must
never be a hard editor rule. *Wiring:* gate guardrail strength on `Evidence.source_tier` in
`render/copilot.py`. *Slots into:* **Phase 0** (the tier field) + a one-line gate.

### 7.3 Make the non-circular contract testable — **[HIGH]**

§6.3 is the whole hybrid, but it is prose. Give it regression teeth: an `examples/adversarial-llm/`
corpus where a planted *claim + excerpt* does **not** deterministically re-derive (the "breaker" the
LLM points at isn't a breaker), and assert the engine **rejects/downgrades** it — the dual of
`resiliency-skills`' `examples/malicious/`. Without this, the re-derivation gate can silently rot
into the circular check it was built to avoid. *Slots into:* **Phase 3/4**.

### 7.4 `lib/signatures` as the shared re-derivation rule — **[MED]**

§6.3 step 2 says "re-derive with the *same deterministic rule* Tier A uses" but leaves "the rule"
abstract. Bind it concretely to a shared **signature library** both tiers consume: re-derivation
becomes "does signature *S* fire at the pointer the LLM proposed?" One `SignatureSet` is cited by
Tier-A (AST) and Tier-B (LLM) alike — which also unifies detection config and makes a new language
*data*, not code. *Slots into:* **Phase 0** (define) / **Phase 4** (consume).

### 7.5 Surface the trust tier in human-facing output — **[MED]**

The reviewer's entire job is triage by trust, yet §6 keeps `source_tier` internal to `Evidence`.
Surface it: `findings`, `REVIEW.md`, and the digest should label each claim **AST-grounded** /
**LLM-proposed-then-confirmed** / **LLM-judgment**. It is the single most decision-relevant column.
*Slots into:* **Phase 0** (carry) + `reporting/findings.py` & the publish REVIEW (surface).

### 7.6 Schema-governance specifics (fold into Phase 1/2) — **[MED]**

§6 implies schema hardening (`needs-human-review` const) but doesn't enumerate it. Concretely:
- **`additionalProperties: false`** on every per-kind schema (a positive allow-list). Ours is loose
  — `riskRationale` was addable to `BlastRadius` precisely because nothing forbade it.
- **`ownership: app | platform | shared`** — we lack it; `resiliency-skills` has it and it is core SRE
  governance (who owns this alert/runbook).
- **`unverified-against-live`** flag for claims uncheckable offline (SLO thresholds, live metrics) —
  while **keeping** our `verified | needs-review | rejected` status (a strength over their
  `needs-human-review: const true`, which we *can* improve on because we ground with hashes).
- A **golden-example-per-kind** corpus validated in CI, mirroring `examples/golden/`.

### 7.7 Push-back on §6 sequencing

- **Phase 1 is not purely "low-risk code."** The scan/publish **credential split** is a
  deployment/process architecture (two contexts that never share state, CI wiring, agent config),
  not a refactor. Track its infra story separately so it isn't under-scoped.
- **Phase 5 (render-adapter breadth) is independent of the trust spine** and is the one piece with
  immediate user-visible value and no LLM-trust risk — run it **in parallel, earlier**, not last.

### 7.8 Net

Adopt §6's spine and ordering over the earlier 4-workstream sketch. The two highest-value additions
are **7.1 (tier-conflict findings)** and **7.2 (tier-aware guardrails)**: both turn assets we already
have — `drift`/`findings` and the editor guardrails — into Tier-B safety nets neither repo has today.

### 7.9 LLM as recall booster (gap-finder) — the primary Tier-B mode — **[HIGH]**

**This is the point of Tier-B for a Java/.NET estate, and it sharpens Phase 4.** §6 framed Tier-B
mostly as *polyglot breadth* ("gaps AST can't *reach*" = new languages). The higher-value mode is
**recall on code we already cover**: things the engine *missed*.

The engine is **high-precision, limited-recall** — it emits only what its deterministic rules match
and hash-grounds every hit, so its real failure mode is **false negatives** (a breaker in a shape we
don't match, a swallow through an unusual path, a timeout that simply *isn't there*). That is exactly
the LLM's strength. The division of labour:

- **Engine = precision gate** — finds what it can prove, grounds it (Tier A, may reach `verified`).
- **LLM = recall booster** — reads the *same* code plus the engine's facts and asks *"what
  reliability-relevant thing is here that the facts don't mention?"*, emitting **candidates** (Tier B).

It is the mirror of the challenge pass: **challenge checks false positives** ("is this claim
grounded?"); **the gap-finder checks false negatives** ("what true claim did we miss?"). Together
they bracket both error types.

**Why it's safe by construction.** Absence-style gaps ("no timeout", "no breaker") can't be
byte-proven the way a present `@CircuitBreaker` can. Those proposals stay Tier-B: they land as
`needs-review` and **only add review candidates — never delete an engine fact.**
Confirmation-style gaps (`swallowed-failure`, `undocumented-job`) can graduate only when the
deterministic engine rule fires at the pointer, at which point the engine, not the LLM, has made the
assertion. Worst case for unconfirmed proposals is noise a reviewer dismisses.

#### Bounded gap taxonomy + a deterministic *refutation* probe per category

Not open-ended LLM rambling — a fixed catalogue, each with a probe that turns "absence" into
"absence-where-we-know-to-look" so the engine kills the easy false positives before a human sees them:

| Gap category | Example | Engine refutation probe (found ⇒ drop the gap) |
|---|---|---|
| `missing-timeout` | critical client, no timeout | search `application.yml` (`resilience4j.timelimiter`), client builder (`setReadTimeout`/WebClient `responseTimeout`) bound to that client |
| `unguarded-critical-dependency` | sync dep, no breaker/fallback | is there a `resiliency.circuitbreaker`/`fallback` fact whose target is this dependency? |
| `swallowed-failure` (recall) | catch that drops an error in a shape the AST matcher missed | re-run the deterministic swallow rule at the proposed pointer — **if it fires, promote to Tier-A**; else Tier-B |
| `data-loss-path` | write-then-publish, no outbox/txn | judgment — route to the oracle (§7.3), no deterministic refute |
| `missing-idempotency` | retried non-idempotent endpoint | judgment |
| `undocumented-job` | cron/scheduled work in no `Flow` | is there a `@Scheduled`/Quartz fact for it? |
| `unbounded-resource` | unbounded cache/queue/threadpool | judgment |

#### Recall eval (the dual of §7.3)

§7.3 tests *precision* (a planted ungrounded claim is rejected). This needs the dual: a fixture with
**known, planted gaps** (a client with a deliberately removed timeout) and an assert that the
gap-finder surfaces them. Without a recall eval we cannot tell signal from noise.

#### Noise budget

Rank candidates by `severity × confidence`; cap per run; run the refutation probes above *before* a
human sees anything. A gap-finder that cries wolf gets muted and the whole tier is wasted.

#### The payoff loop: confirmed gaps graduate to Tier-A

The strategic part. A recurring, human-confirmed gap category is a signal to add a **deterministic
collector/signature** for it: LLM finds it (Tier-B) → human confirms → engineer adds a signature →
next run it is Tier-A, hash-grounded, and the LLM moves to the next frontier. **The gap-finder drives
the engine's recall upward over time** instead of being a permanent crutch. (Pairs with 7.4: the
signature *is* the re-derivation rule.)

### 7.10 Worked example — `assess-resiliency` in gap-mode

A concrete first Tier-B collector, so Phase 4 has an instance, not just a category.

- **Targets:** every critical synchronous dependency the engine knows about — `Dependency` facts and
  `http-egress` flow steps — that has **no** `resiliency.circuitbreaker`/`fallback`/timeout fact.
- **Input (framed untrusted via `synth/context_pack.py`):** those dependency/flow facts + the cited
  client and config code. The LLM is told the engine's coverage so it doesn't re-report hits.
- **LLM emits (pointer, not fact):** `{category: unguarded-critical-dependency, target: inventory-client,
  excerpt: "<the call site text>", rationale: "no timeout/breaker around a sync call to a critical dep"}`.
- **Engine refutes or stamps:** locate the excerpt → `path:line:hash`; run the `missing-timeout` /
  `unguarded-critical-dependency` probes (search `application.yml` + the client builder). Found ⇒ drop
  (false gap). Not found ⇒ emit a Tier-B `BlastRadius`/finding `status: needs-review`,
  `source_tier: llm`, with `checked: [application.yml, <client>.java]` so the absence is honest.
- **Cross-check (§7.1):** if the engine *did* emit resiliency for that target but the LLM flags it →
  `tier-conflict` (may reveal an engine bug). **Guardrails (§7.2):** this finding is advisory in the
  editor, never a hard "don't remove" rule, precisely because it's Tier-B.
- **Graduation (§7.9 loop):** if "missing-timeout on WebClient builders" recurs and is confirmed, add
  a deterministic timeout-config collector — it becomes Tier-A and drops out of the LLM's frontier.

---

## 8. Implementation status (2026-06-08)

Tracked against the §6 phase table. Legend: ✅ done · 🟡 partial · ⬜ not started. **380 tests
passing, ruff-clean** (review-tail hardening + R6 observability-coverage gap-finder). Every claim below was re-verified at
file:line — no drift; corrections were *additions* for behaviors the code had but this section
under-documented (folded in where they belong).

**Consolidated status — phases, Round-3 (R*), and competitive-review (N*) items.** Single table so
the three review docs don't each carry their own tracker (they're now historical snapshots; see the
status-authority note at the top):

| Track | Item | Status | Landed |
|---|---|---|---|
| Phases 0–3 | trust tiers · hardening · status-aware spine · challenge loop | ✅ | |
| Phase 4 | Tier-B gap-finder, wired into `run` | ✅ | |
| Phase 5 | render-adapter breadth | ✅ 6/6 backends (prom/splunk/wavefront/appd/grafana/thousandeyes) | |
| §7.1–7.6 | tier-conflict findings · tier-aware guardrails · adversarial corpus · shared signatures · trust surfacing · schema governance | ✅ | |
| R1–R3 | `Criticality` kind · severity floor · `sre-criticality` skill | ✅ | #24 |
| R5 | Tier-A parameter-completeness gaps | ✅ | #24 |
| R4 | publish clobber-protection manifest | ✅ | #25 |
| N1 | secret-scan non-UTF-8 fail-open (**bug**) | ✅ | #26 |
| N2 | multi-window/multi-burn-rate alerts (long **and** short window) | ✅ | #26 |
| N3 | `bulkhead` / `rate-limit` / `idempotency` signatures | ✅ | #26 |
| R6 | observability-coverage Tier-B skill + fact-based refutation probe | ✅ | |
| R7 | grafana + thousandeyes adapters | ✅ 6/6 | |
| R8 | supply-chain (`--require-hashes` + Renovate digest-pin + `detect-secrets`) | 🟡 offline wheel done; rest open | |
| N4 | central `taxonomy.yaml` + severity-vocab reconciliation | ✅ | #37 |
| N5 | inventory signatures · load-shed/backpressure probes · findings narrative | ✅ | #38–41 |
| infra | full scan/publish credential split (§9.3 #5) | 🟡 scan role done; publish role + CI open | gate before live publish |

The per-phase detail below remains the authoritative narrative for each ✅.

### Phase 0 — Fact contract & trust tiers ✅

- `Evidence.source_tier` (`"ast"` default | `"llm"`) on the provenance model + the envelope schema
  (optional `enum`, so artifacts without it still validate).
- `ScanContext.evidence(...)` stamps `source_tier`; a keyword-only param lets a future Tier-B
  collector pass `"llm"`.
- `CollectorProtocol` (runtime-checkable) that both shapes — `collect(ctx)` and `collect(ctx, fs)` —
  satisfy.
- Per-artifact `tier` + a `by_tier` roll-up surfaced in the validation report.
- Pure plumbing: no artifact status/confidence/content changed.

### Phase 1 — Adopt `resiliency-skills`' hardening ✅ (code-complete)

Both weaknesses §6 assigns to Phase 1 are closed, and the §6 hardening list is implemented in code:

- **Non-escapable injection fence** (`synth/context_pack.py`) — fence/sentinel runs in cited
  excerpts + paths are defanged, so hostile source can't break out of the untrusted block (§4).
- **Sanitized renderers** (`render/copilot.py`) — untrusted values in guardrails/runbooks are
  flattened + de-backticked (diagrams were already sanitized).
- **Publish-repo allowlist** (`publish/forge/github.py`, `publish.allowed_repos`) — live publishes
  confined to an allowlist; empty list = block-all by default (§4 publish path).
- **Token out of `git` argv** — tokenless remote + auth via env config (`GIT_CONFIG_*` /
  `http.extraheader`).
- **fail-closed secret gate** (`security/secret_scan.py`) — `enforce_secret_gate()` scans the staged
  tree and raises on any match (surfaced for review, not silently scrubbed); `redact_tree()` runs
  only under the explicit `--allow-secrets` override.
- **Fan-out cap** (`publish.max_artifacts`) — refuses a runaway/compromised PR tree.
- **Dangerous-pattern safety lint** (`validation/safety.py`) — artifact specs are scanned for
  shell-pipe-to-network, `rm -rf`, TLS/auth-disable, and dynamic-eval patterns; a hit forces the
  artifact to `needs-review` in the orchestrator gate even when provenance is clean (a de-facto
  gate-strength layer, surfaced by the §9 re-audit).
- **Markdown-level injection defense** — the runbook renderer (`render/copilot.py:_inline`)
  de-backticks/flattens every field, so untrusted text can't break out of a code span in the
  generated markdown (beyond the guardrail sanitization above).
- `needs-human-review` const — satisfied by our existing `verified | needs-review | rejected`
  status (§7.6 keeps ours over their const).

Deferred (tracked, not dropped) — infra, not engine code:

- **Full scan/publish credential split** — the **no-credential scan role landed** (read-only
  `sre-target-scan` agent); the scoped publish role + CI wiring remain deployment/infra per §7.7.
  Code-side pieces (allowlist, token-out-of-argv) were already done.
- **Supply-chain pinning** — schemas + config now ship as package data (a self-contained,
  air-gappable wheel), but GitHub Actions are still tag-pinned (not SHA-pinned) and deps are
  floor-pinned (not hashed); `resiliency-skills`' Renovate digest-pin + `--require-hashes` is the lift.

(§7.6 schema governance, originally slotted here, is **done** — see below.)

### Phase 2 — Status-aware trust spine ✅

- **Status-aware crossref** (`validation/crossref.py`) — a verified artifact that depends-on/implements
  a non-verified (or missing) referent is downgraded to needs-review, iterated to a fixpoint so the
  downgrade cascades. Monotonic/downgrade-only; only trust-dependency relations trigger it (back-links
  like alerts-on/covers don't). The orchestrator gating loop is now compute → downgrade → persist.
- **Provenance path confinement** (`validation/provenance.py`) — evidence paths must resolve inside the
  repo root (`is_relative_to`); `../` and absolute-path escapes are rejected.
- **Status-aware readiness** (`scoring/readiness.py`) — artifact-presence checks credit only verified
  coverage; a needs-review draft is a gap ("present but not yet verified"), never counted toward the
  grade. Recomputed in the orchestrator *after* gating so a downgrade is reflected.

### §7 enhancements landed alongside

- **§7.1 tier-conflict findings** ✅ — when Tier-A and Tier-B assert opposite presence for the same
  (concern, target), the validation report flags a `tier-conflict` instead of dropping the Tier-B
  signal (`reporting/findings.py`) — a near-zero-cost detector for Tier-A extraction bugs. Dormant
  until a Tier-B producer.
- **§7.2 tier-aware guardrails** ✅ — only Tier-A findings emit hard Copilot rules; Tier-B surfaces as
  advisory notes (`render/copilot.py`).
- **§7.3 non-circular contract testable** ✅ — an adversarial-LLM corpus
  (`tests/fixtures/adversarial-llm/`) of planted claims the cited code doesn't support; the challenge
  gate must reject/downgrade each (`tests/test_adversarial_llm.py`). Regression teeth before a live
  oracle — the dual of `examples/malicious/`. (Prerequisite for Phase 3.)
- **§7.4 shared signatures + re-derivation** ✅ — `sre_kb/signatures.py` is one library both tiers
  read: a `Signature` carries the annotation keys (Java AST) and call tokens (.NET AST) the Tier-A
  collectors key off, plus the text patterns Tier-B re-derives with. The challenge gate re-derives a
  ResiliencyPattern claim via "does the signature fire at the pointer?" not a substring, and
  `rederive()` is the Tier-B contract (§6.3 step 2) the Phase 4 gap-finder calls. One rule, both tiers.
- **§7.5 surface the trust tier** ✅ — the findings digest + PR `REVIEW.md` label each claim
  AST-grounded / LLM-proposed, with a by-tier roll-up. A shared `tiers.py` is the single source of truth.
- **§7.6 schema governance** ✅ — `additionalProperties: false` on every per-kind spec (positive
  allow-list), an `ownership` enum (app|platform|shared) and an `unverifiedAgainstLive` flag on the
  envelope, a golden-example-per-kind corpus, and a registry guard that fails CI when a registered
  kind points at a missing schema or lacks a golden example (`tests/fixtures/golden/`,
  `tests/test_golden_corpus.py`).

### Phase 3 — Challenge loop (Copilot oracle) ✅

Built and exercised end-to-end (2026-06-07): a deterministic `GroundingChallenger` runs inline in the
orchestrator; `build_worklist` emits judgment-call claims (Alert appropriateness, Runbook safety) to
`challenge/worklist.json`; `challenge-worklist` shows them; Copilot adjudicates
(`supported|unsupported|contradicted`); `challenge-apply` re-gates with the **same monotonic
downgrade-only** rule and moves each artifact to its new status dir. The in-process `LLMChallenger`
class stays a **dormant hook** — the oracle is Copilot via the worklist, so the engine never calls a
model (the founding invariant). The §7.3 adversarial-LLM corpus is the regression harness.

> Verified live: on `sample-spring-pcf` the loop routed the `create-order-latency-burn-rate` Alert
> `verified → needs-review` when its burn-rate expr didn't measure the latency SLI it cited (now fixed).
>
> Two follow-on fixes hardened that derivation (`synth/scaffold.py:burn_rate_expr`): a latency SLO now
> burns on its histogram buckets (`*_bucket{le=<threshold>}`) rather than the request error ratio, and
> the burn-rate is **scoped to the flow's own route** (`uri="…"`) so a per-flow SLO is no longer
> measured service-wide. Covered by `tests/test_burn_rate_expr.py`.

### Phase 4 — Tier-B LLM gap-finder 🟡 (spike)

The first Tier-B collector, as a spike (`docs/PHASE-4-GAP-FINDER.md`). Copilot proposes resiliency
gaps the AST missed (§7.9 recall mode), quoting verbatim excerpts; the engine — never the LLM —
locates each (`collectors/llm/gap_finder.py`), stamps `path:line:hash`, and runs deterministic
probes via the shared `signatures.py` (§7.4) / AST detectors. Refutation-probe absence gaps
(`missing-timeout`, `unguarded-critical-dependency`) survive only when the relevant signature fires
nowhere checked, then scaffold as `ResiliencyGap` `needs-review` / `source_tier=llm`.
Confirmation-probe gaps (`swallowed-failure`, `undocumented-job`) graduate only when the
deterministic rule fires at the pointer, then scaffold as `source_tier=ast` and can verify. The
recall eval and real assistant validation fixture (`tests/test_gap_finder.py`,
`tests/test_copilot_gap_validation.py`, the dual of §7.3) now measure four planted gaps plus
shipping/refunds controls. Prompt: the vendored `assess-resiliency` skill
(`.github/skills/sre-gap-finder/`). CLI: `sre-kb gap-finder`.

Grounded probes today: `missing-timeout` and `unguarded-critical-dependency` refute absence claims
when `circuit-breaker`/`fallback`/`timeout` fire; `swallowed-failure` and `undocumented-job` are
confirmation probes that graduate only when the deterministic rule fires at the pointer. Judgment
categories (`data-loss-path`, `missing-idempotency`, `unbounded-resource`) are citation-grounded and
routed to review, never auto-verified. The collector also has **target-scoped** config probing (by
resilience instance name) and a **noise budget** (`gap_finder.max_candidates`, severity-ranked).
Integration into the main `run` pipeline is **done** (§9.3 item 1): `run` auto-detects
`.sre/gap-proposals.json` and routes survivors through the shared gate; the standalone
`sre-kb gap-finder` CLI remains for proposals-only runs.

### Phase 5 ✅ (render-adapter breadth)

The neutral-intent → adapter seam is in (`render/alerts.py`): an `Alert`'s `spec.expr` is built from a
tool-neutral `BurnRateIntent`/`LogPatternIntent` and rendered through per-backend adapters, selected
by config (`render.alert_tools`). Adding a backend is a new adapter, not a change to extraction /
scaffold / gating. Backends today:

- **Prometheus** (PromQL) and **Splunk** (SPL) — byte-grounded dialects, output unchanged from before
  the refactor (pinned by `test_burn_rate_expr.py` + `test_e2e_scan.py`).
- **Wavefront** (WQL) — availability burns as a faithful moving-window error-fraction ratio
  (`msum`/`rate`/`ts`); latency renders as a labelled p-threshold (Micrometer's Wavefront registry has
  no `le`-bucket series), explicitly *not* a budget burn-rate.
- **AppDynamics** — a structured **Health Rule** fragment (metric path + condition), since AppD alerts
  via health rules, not a query language; the tier/BT is templated for the reviewer to map.
- **Grafana** — unified-alert rules over a datasource: burn-rate reuses the deterministic Prometheus
  PromQL against a Prometheus datasource (fidelity equals Prometheus), log alerts render as Loki LogQL;
  the datasource UID is a `REPLACE_ME__` sentinel.
- **ThousandEyes** — a synthetic HTTP Server test alert rule (metric + condition, not a query), since
  synthetic monitoring has no passive request histogram or budget burn-rate; the covering test IDs are
  templated for the reviewer, labelled a static threshold, not a burn-rate.

"Honest coverage": an adapter emits a backend only where it maps faithfully to the intent, and labels
the mechanism wherever it differs from a multi-window burn-rate (`tests/test_alert_adapters.py`).

**Lifted from `resiliency-skills` (source-verified re-audit, §9.6):** their `AlertIntent` schema has a
better-factored tool-neutral spec, so we adopted its *model* onto our envelope — the `Alert` spec now
also carries `class` (symptom|cause), a `signal` object, a structured `burnRate`
(`sloRef`/`sli`/`shortWindow`/`longWindow`/factors/`budgetFraction`), and `renderTargets` (the
backends actually rendered). We did **not** copy their JSON: their governance (`needs-human-review:
const`, enum confidence, file-level `path`) stays *weaker* than ours, so the adopted spec rides our
byte-grounded `evidence`, numeric `confidence`, and `status` model — each repo contributes its
strength. (`schemas/v1alpha1/Alert.schema.json`; `tests/test_e2e_scan.py`.)

The four backends above cover the team's current monitoring stack (Prometheus + Splunk + Wavefront +
AppDynamics); the seam makes any further backend a drop-in adapter if the stack changes.

**`Dashboard` kind adopted** (from resiliency-skills' `dashboard` schema, on our envelope): the
scaffolder emits a per-service `Dashboard` with the standard RED panels (rate/errors/duration) as
deterministically generated Prometheus queries scoped to the flow's route, `needs-review` +
`unverifiedAgainstLive` (`render/dashboards.py`; `schemas/v1alpha1/Dashboard.schema.json`;
`tests/test_dashboards.py`). Per-backend dashboard rendering (Grafana/Wavefront) is the next step.

Deferred: per-backend dashboard rendering beyond Prometheus and diagram render adapters; and verifying
the Wavefront/AppDynamics metric names against a live tenant (they carry `unverifiedAgainstLive` like
all metric alerts).

### Adopted kind — `ScheduledJob` (P2 breadth, from the resiliency-skills re-audit)

Their `jobs` schema → our **`ScheduledJob`** kind (the registry already reserved the row). A
`@Scheduled` collector (`collectors/java_spring/jobs.py`) emits one **byte-grounded, verified**
`ScheduledJob` per job (cron vs fixed-rate, the trigger method, concurrency). This gives recurring
jobs **Tier-A** coverage and pairs with the gap-finder's Tier-B `undocumented-job` probe, which
flags jobs *no* collector reaches — so as this collector grows, that probe's recall shrinks (the
§7.9 graduation dynamic). `schemas/v1alpha1/ScheduledJob.schema.json`; `tests/test_jobs.py`.

### Adopted kind — `Criticality` + the deterministic severity floor (Round-3 R1–R3)

The reliability model behind `resiliency-skills`' breadth that the §9.6 audit had not mined (the
Round-3 review, now folded here). Their `criticality`
schema + `TIER_SEVERITY_FLOOR` → a grounded **criticality reliability spine** on our envelope:

- **R1 — `Criticality` kind + collector** (`collectors/common/criticality.py`,
  `schemas/v1alpha1/Criticality.schema.json`). `tier`/`businessCriticality` are read from an
  authoritative repo-local declaration (`.sre/criticality.yaml`) and cited to its own line (Tier-A,
  verified); `dataClassification` (pii/pci) is **re-derived deterministically** from PII/PCI
  signatures in code (byte-grounded). Self-gating: no declaration and no PII/PCI signal → no
  artifact, so the spine is inert on a plain repo.
- **R2 — deterministic alert severity floor** (`render/alerts.py:effective_severity` +
  `TIER_SEVERITY_FLOOR`). A service's criticality tier raises alert severity to a floor (tier0 →
  `critical`) and can never lower a declared severity. Paging severity no longer rides a judgment
  call — but **only a byte-grounded (Tier-A) tier feeds the floor**; an LLM-proposed tier stays
  advisory (§7.2). Wired into both Alert scaffolders.
- **R3 — Tier-B `sre-criticality` skill** (`.github/skills/sre-criticality/`, vendoring their
  `assess-criticality-and-data`). The prompt half: Copilot proposes a tier/dataClassification to
  `.sre/criticality-proposal.yaml`; the engine re-derives dataClassification via the same signatures
  and lands the proposed tier `needs-review`, `source_tier=llm` — never feeding the floor. The
  non-circular contract applied to criticality.

`tests/test_criticality.py` (13 tests: the floor is up-only; a grounded tier0 floors the burn-rate
Alert to `critical`; a *proposed* tier0 stays `needs-review` and does **not**).

### Adopted recall — parameter-completeness gaps (Round-3 R5)

The deterministic dual of the Tier-B absence gaps (§7.9): a resilience pattern can be *present* yet
under-specified. `collectors/java_spring/resiliency_params.py` reads each `@CircuitBreaker`/`@Retry`
annotation plus the *resolved* resilience4j config (instance → `base-config` → implicit
`configs.default`) and emits a **Tier-A** `resiliency.gap` when a load-bearing param is unconfigured:
`circuit-breaker-without-thresholds` (no `failure-rate-threshold`) and `retry-without-backoff` (no
`wait-duration`/backoff — retry-storm risk). These flow through the same `scaffold_gap` gate as the
Tier-B gaps but carry `source_tier=ast` / `rederivation=param-completeness`, so they can **verify** —
no LLM involved. This is exactly the graduation target §7.9 describes (a recurring category becomes a
deterministic rule). Timeout-duration completeness is deferred (a `@TimeLimiter` has a library
default; the Tier-B `missing-timeout` probe covers timeout *absence*). Inert on a fully-configured
service. `tests/test_resiliency_params.py` (4 tests, incl. config-layering resolution).

### Engine-owned clobber-protection on publish (Round-3 R4)

A re-publish must never silently revert an operator's edit to a generated file. `publish/manifest.py`
records the hash of every file the engine writes in `.sre/manifest.yaml` in the target repo; the
GitHub forge runs a manifest-backed **3-way merge** against the cloned target instead of a blind
overwrite (the old `_sync_tree` is gone): unchanged files refresh in place, an operator-edited file is
preserved with the fresh draft routed to `.proposed/<path>`, and orphaned outputs are pruned (unless
operator-edited). The cloned target is the only place the operator's current files exist in our
PR-based model (adopted from resiliency-skills' in-tree `assemble`). `tests/test_publish_manifest.py`
(6 unit + 1 end-to-end through the forge). **261 tests green** (after #25 R4 + #26 review fixes).

### Publish-repo hardening + self-contained engine (publish-hardening slices)

Generated target repos now carry guardrails at the **repo root** (where GitHub honors them): a
`validate-sre-kb` CI workflow that runs `validate-kb` over `catalog/*/kb` plus a fail-closed
`secret-scan`, a `CODEOWNERS` sentinel, and a PR template — alongside vendored schemas + a pinned
engine version. The forge stays the **sole** clobber-merge authority (R4); the staging step is a
clean re-stage, not a second merge (an earlier slice's local merge that leaked a per-service
`.sre/manifest.yaml` was removed). The secret ruleset gained provider classes
(Stripe/Slack/SendGrid/npm/PyPI/`Authorization: Basic`/Azure) + a DoS budget, and `value-shape` no
longer trips on content hashes. Schemas **and** config now ship as package data, so a
wheel-installed engine is self-contained. The read-only `sre-target-scan` agent delivers the
no-credential scan role. **Gate a live (`--no-dry-run`) publish on R8** (SHA-pinned Actions +
`--require-hashes` + an independent second gate) and a real engine release.

---

## 9. Reassessment & revised forward order (2026-06-07, post-spike)

A re-audit once the Phase 4 spike had landed and merged to `main`, on two axes: (a) a source-level
re-verification of every §8 claim, and (b) a strategic re-read of the plan now that the spike
*exists* rather than being the open risk it was framed as.

### 9.1 The plan's central bet has cleared its bar

The whole plan was sequenced around one make-or-break experiment — the fenced Tier-B gap-finder
(§6.3, §7.9). If the *non-circular contract* couldn't be made to work, "just extend
`resiliency-skills`" was the rational alternative (the earlier reassessment's framing). The
spike resolved it: its recall eval **surfaces a planted gap, refutes a false positive** (a timeout
*is* present → the shared signature fires → the gap is dropped), and **drops a hallucinated citation**
(anchor not found verbatim) — and the probe generalizes across Java *and* .NET. The architecture is
now *demonstrated*, not argued; that strategic question is closed in the plan's favor.

### 9.2 Deep-review verdict — §8 is trustworthy, and slightly understated

Every Phase 0–4 claim in §8 was re-verified at file:line: **zero drift.** The audit also surfaced
behaviors the code has but §8 hadn't recorded — now folded in: the dangerous-pattern **safety lint**
(`validation/safety.py`), **markdown-level injection defense** in the runbook renderer, the
honest-negative **`checked:` trail** on gap Facts, and the **`provenanceMode`** (`deterministic` |
`llm-asserted`) signal on the envelope. None change status; they make the doc match the code.

### 9.3 The revised order — *integrate before expand*

Phases 0–3 and every §7 enhancement are done and tested (227 green). What remains is **finishing a
proven architecture**, not de-risking an unproven one — which reorders the work. (This also finally
takes §7.7's standing advice that Phase 5 is independent and should run in parallel, not last.)

1. **Wire the gap-finder into `run`.** ✅ **Done.** `sre-kb run` now re-grounds any
   `.sre/gap-proposals.json` and surfaces the survivors as `ResiliencyGap` artifacts through the
   *same* validate/challenge/gate path — merged into `facts.jsonl` (so the §7.1 tier-conflict check
   sees them). Refutation-probe survivors land `needs-review`, `source_tier=llm`; confirmation-probe
   survivors can graduate to `source_tier=ast` and verify. A complete no-op when no proposals file
   exists. (`pipeline/orchestrator.py`; `tests/test_run_gap_integration.py`.)
2. **`swallowed-failure` confirmation probe** (the 3rd probe). ✅ **Done** (PR #14): the first
   *confirmation*-class probe — the deterministic swallow rule firing at the LLM's pointer *confirms*
   the gap and **graduates it to Tier-A** (`source_tier=ast`, verified-eligible). The cleanest
   graduation exemplar; see §9.4 status and §9.5 ④ for the trust-boundary note.
3. **Graduation loop (§7.9).** ✅ **Done.** A reviewer records verdicts with `sre-kb confirm-gap`
   (tallied in the target repo's `.sre/graduation-tracker.yaml`); once a category reaches the
   threshold (`graduation.confirmation_threshold`, default 5) with zero false positives, `sre-kb
   graduation-candidates` flags it and **drafts the deterministic signature for a human to review and
   merge** — assisted, never auto-applied. So a recurring, human-confirmed gap category becomes an
   engine signature and the gap-finder *ratchets recall upward* instead of being a permanent crutch.
   The strategic core of Tier-B. (`graduation/`, `tests/test_graduation.py`.)
4. **Phase 5 render-adapter breadth.** ✅ **Done** (parallel track). The neutral-intent → adapter
   seam plus Prometheus/Splunk/Wavefront/AppDynamics + Grafana/ThousandEyes alert backends have landed
   (6/6; §8 Phase 5), and dashboard panels render for Prometheus/Grafana/Wavefront (splunk/appd panels
   carry the metric but no RED query — no faithful dialect). Independent of the trust spine, zero
   LLM-trust risk.
5. **Infra hardening** (full scan/publish credential split; supply-chain SHA-pinning +
   `--require-hashes`). Gate on intent to do **live (`--no-dry-run`) publishes** — it is the one open
   item that becomes a real safety bug the moment someone ships against a real target.

Net: (1) makes Tier-B real for users, (2)+(3) make it compound, (4) runs alongside, (5) lands before
the first live publish. The §6 phase *table* records the original sequence; this subsection is the
current one.

### 9.4 Work note — priority 2 (`swallowed-failure` probe + graduation exemplar)

Scoped here so it can be picked up independently (e.g. in parallel with priority 4, which it does
**not** overlap — see the collision map below). Priority 1 (the `run` integration it builds on) is
done.

**The key design point — it's a *confirmation* probe, not a refutation probe.** The two existing
probes (`_REFUTING_CONCERNS` in `collectors/llm/gap_finder.py`) ground an *absence*: a gap survives
only if the refuting signature fires **nowhere** checked. `swallowed-failure` is the opposite — the
deterministic swallow rule firing **at the LLM's pointer confirms the gap** (and is exactly what lets
it graduate). So this needs a second probe class alongside `_REFUTING_CONCERNS`, e.g.
`_CONFIRMING_CONCERNS`, with inverted survival logic.

**Graduation behavior (the exemplar).** When the swallow rule fires at the located pointer, the
finding is no longer LLM-asserted — the engine itself re-derived it. Stamp it `source_tier=ast`
(Tier-A) so it can reach `verified` through the normal gate, rather than being forced to
`needs-review` like an unconfirmed Tier-B gap. A pointer where the rule does **not** fire is dropped
(the LLM can't assert a swallow the engine can't reproduce). This is the smallest concrete instance
of the §7.9 graduation loop and the thing priority 3 will generalize.

**Touchpoints (where the work lives):**
- `collectors/llm/gap_finder.py` — add the confirming-probe branch; reuse `_locate` for the pointer.
- `parsing/code_model.py` — the deterministic rule already exists: `_enclosing_swallow` (and the
  `swallowed.failure` fact type). The work is running it *at a byte-offset pointer* (offset → AST
  node), not re-implementing detection.
- `pipeline/gap_finder.py` / `scaffold_gap` — allow a confirmed (Tier-A) swallow gap to carry the
  promoted tier/status instead of the hard-coded `needs-review` / `confidence 0.5`.
- Tests: extend the recall eval — a planted swallow in a shape the AST matcher missed → **promoted to
  Tier-A/verified**; a pointer with no swallow → dropped. Add a fixture proposal of category
  `swallowed-failure` to `tests/fixtures/sample-gap-finder/.sre/gap-proposals.json` or a sibling.

**Collision map (for parallel work):** priority 2 touches `collectors/llm/`, `parsing/code_model.py`,
and `pipeline/gap_finder.py`. Priority 4 (render adapters) touches `render/` and
`synth/scaffold.py` — **fully disjoint**, safe to run concurrently. The only shared surface across
all remaining tracks is the schema/registry (a new gap shape or kind), so coordinate there if both
add artifact kinds at once; the Python modules don't overlap.

> **Status (priority 2 — done):** the `swallowed-failure` **confirmation probe** is built
> (`_CONFIRMING_CATEGORIES` / `_confirm_swallow` in `collectors/llm/gap_finder.py`). A swallow the
> rule reproduces at the pointer graduates to `source_tier=ast` and reaches `verified` through the
> normal gate (`scaffold_gap`); a pointer where it doesn't fire is dropped. Recall eval extended in
> `tests/test_gap_finder.py` (planted non-messaging swallow → verified; no-swallow pointer → dropped).
> One framing correction vs. the note above: the value is **not** "re-run the existing rule" (it
> already runs on every call) — it is *emitting a swallow finding for the call sites the collectors
> ignore* (everything but Kafka egress). See §9.5 ③.

### 9.5 Risks & open questions — what this reassessment might be wrong about

§9.1–9.2 are confident; this subsection is the deliberate counterweight. The §9.2 audit was a
*consistency* check (does the code match §8) — **not** an adversarial soundness review. These are the
things most likely to be wrong, roughly by impact:

1. ~~**The LLM half has never actually run.**~~ **Closed for the sample target.** A real Copilot
   run using `.github/skills/sre-gap-finder/SKILL.md` produced
   `tests/fixtures/sample-gap-finder/.sre/gap-proposals.json`; the checked-in validation report at
   `tests/fixtures/sample-gap-finder/.sre/gap-validation-report.json` measured
   expected/proposed/grounded/kept/confirmed all at 4, with proposal/kept recall and precision all
   `1.00` and no false-positive survivors. This demonstrates the full manual boundary: model writes
   pointers, engine locates/re-derives, validation reports raw and post-grounding quality.
2. **"Signal vs noise" is measured only on the sample.** The run above proves useful recall and no
   false-positive survivors on one real-ish fixture; it still says nothing about false-positive rate
   at service/repo scale. The noise budget (§7.9) is a knob with only fixture-level evidence.
3. **The §9.4 swallow rationale was misleading (now corrected).** "Re-run the existing rule at the
   pointer" adds nothing alone — `_enclosing_swallow` already runs on every call; `swallowed.failure`
   *facts* are emitted only for Kafka egress (`java_spring/annotations.py`). The recall comes from
   emitting a finding for the **non-messaging** call sites the collectors skip. Verified at source.
4. **Graduation widens the trust boundary (conscious decision).** A confirmed swallow becomes
   `source_tier=ast` and can reach `verified` → it then drives **hard** Tier-A guardrails (§7.2). So
   an **LLM-chosen location** can now produce a hard rule. It is sound (the engine's deterministic
   rule fired on hashed bytes; the LLM can only point at a *real* swallow, never fabricate one) — but
   it is a real change from "nothing the LLM touches auto-verifies," and should stay conscious.
5. **Re-derivation soundness rides on the shared signatures — two precision holes now fixed.**
   ~~The `fallback` signature is a bare `"fallback"` substring → it matches the word in a code
   comment and can refute a real gap; the config target-scope is a substring match → can false-match
   (`payments` ⊂ `payments-api`).~~ **FIXED:** the `fallback` signature now matches a fallback
   *mechanism* (`fallbackMethod=`/`@Recover`/`.Fallback(`/`.withFallback(`/Feign `fallback=`), never
   the bare word, and config scoping is a **whole-token** match (`payments` no longer scopes into a
   `payments-api` block) — `signatures.py`, `collectors/llm/gap_finder.py:_name_in_text`, with
   regression tests `test_fallback_signature_matches_mechanisms_not_the_bare_word` and
   `test_config_scope_matches_whole_instance_token_not_prefix`. Residual (by design): the catalogue is
   still text-based — broaden it to more stacks as Tier-B leans harder; the two holes that could drop
   a real gap are closed.

### 9.6 Source-verified competitive re-audit (2026-06-07) + lift actions

A full clone of `resiliency-skills` @ `f99e028` (not the public-surface skim §1–§5 was), to refresh
the stale comparison and act on it.

**Confirmed unchanged:** still **8 signatures** (5 framework + 3 messaging; no datastore/infra/
observability detectors) and **18 skills**. **Still not byte-grounded** — provenance is now a
*required* governance block (`repo/commit/scanDate/skill`) with an optional file-level `source.path`,
but no line/excerptHash/verbatim re-verification (their hashing is clobber-protection for generated
output, not source grounding). Our byte-grounding differentiator holds.

**Corrections to the surface read — they are ahead on two axes:**
- **Render breadth.** A first-class `AlertIntent` schema + **six** Jinja adapters
  (`prometheus, splunk, wavefront, appdynamics, grafana, thousandeyes`) vs our four. Nuance in our
  favor: their adapters pass through an LLM-supplied `signal.query`; ours *deterministically generate*
  the query. Fat-engine vs fat-skills, in the render layer.
- **Supply-chain hardening.** `engine/requirements.lock` uses pip `--require-hashes` and `renovate.json`
  pins Actions to commit SHAs — exactly our deferred §9.3 #5.

**Lift actions:**
1. ✅ **AlertIntent model adopted** onto our envelope (this PR) — `class`/`signal`/`burnRate`/
   `renderTargets` on `Alert.spec`, byte-grounded (see Phase 5 above).
2. ✅ **`grafana` + `thousandeyes` adapters adopted** — backend support now 6/6 (`render/alerts.py`),
   available via `render.alert_tools` (opt-in, not default-on). See Phase 5 above.
3. ⬜ **Lift their supply-chain config** (`--require-hashes` lockfile + Renovate digest pinning) to
   close §9.3 #5 / Phase 1 deferred — it is proven and directly portable.

**Caveats:** their engine tests didn't run in the audit env (deps), so their suite's green state is
unverified; their "reliability model" batch was not deep-read.

### 9.7 Open backlog (folded from the retired review docs)

The single live list of what's left, consolidated from the now-retired Round-3 / competitive
reviews. Completion is tracked in the §8 table; the rationale lives here.

- **R6 — `observability-coverage` Tier-B skill + refutation probe. ✅ Done.** The
  `sre-observability-coverage` skill (`.github/skills/`) scores metrics/logs/traces/synthetics
  `covered|partial|missing` and proposes the missing pillar as a byte-anchored gap; the gap-finder
  adds four categories (`missing-metrics`/`-tracing`/`-structured-logging`/`-synthetic-monitoring`)
  that **refute against the engine's own facts** — a claimed-missing pillar dropped when the facts
  already prove it present (`config.actuator`/`config.slo` or a micrometer/actuator/prometheus dep →
  metrics; a sleuth/OTel/zipkin/brave dep → tracing; a JSON/correlation `observability.logging` fact →
  structured logging; synthetics has no engine signal, so it always routes). Unlike the §7.4 code
  signatures, the refutation reads the **fact set** the deterministic collectors already produced, so
  it can't drift; survivors land Tier-B `needs-review` (reusing the `resiliency.gap` → `ResiliencyGap`
  path, anchored on the config/build line). Logging posture folds in as the structured-logging signal,
  not a separate skill. The orchestrator threads its fact set into the gap-finder; the standalone CLI
  runs without one (grounds + routes, no fact-refute). *(NB: `readiness.py` still hard-codes
  `tracing-enabled: False`; wiring it to the same dependency check is a small follow-up.)*
- **R7 — `grafana` + `thousandeyes` alert adapters. ✅ Done.** Backend parity reached 6/6 via the
  neutral-intent → adapter seam (`render/alerts.py` `_grafana_burn`/`_grafana_log`/`_thousandeyes_burn`):
  the engine lifts each backend's template *structure* and feeds its own deterministically generated
  query, never an LLM-supplied `signal.query`. See §9.6 lift action #2.
- **R8 — supply-chain hardening.** ✅ **offline wheel landed** — `make offline-wheel` /
  `scripts/build-offline.sh` builds a self-contained wheelhouse (engine + every runtime dep; schemas +
  config ship as package data). Still open: `--require-hashes` lockfile + Renovate digest-pin of
  Actions + an independent `detect-secrets` second gate. See §9.6 #3 / §9.3 #5. Gate before any live
  (`--no-dry-run`) publish.
- **N4 — central vocabulary + severity reconciliation.** ✅ **Done.** `schemas/taxonomy.yaml` is the
  single source of truth for the recurring vocabularies (severity, status, source_tier, ownership,
  criticality tier, data classification); `sre_kb/taxonomy.py` exposes them + `reconcile_severity`
  (sevN/pN/blocker/numeric → our `critical/high/medium/low`). The severity-rank/floor constants are
  derived from it, and `tests/test_taxonomy.py` sanctions the known severity shapes and fails on any
  new schema/code enum drift.
- **N5 — lower priority. ✅ Done.** Three data-driven breadth paths plus the named injection fixtures:
  - **Declarative inventory signatures** (`sre_kb/inventory_signatures.py`, #39) — an ordered catalog
    mapping a dependency name → datastore engine / message-broker kind, and a repo's manifest files →
    (language, runtime, buildTool). Detection is data, not code (same philosophy as `signatures.py`), so
    the `TechStack` roll-up now covers a Node or Go service the AST collectors don't parse, citing its
    manifest; `synth/inventory.py` and `estate/topology.py` consume the shared catalog.
  - **`load-shed`/`backpressure` vocab + judgment probes** (#40) — two cross-stack signatures
    (mechanism-shaped, never a bare word, so a false fire can't silently drop a real gap, §9.5 ⑤), with
    `missing-backpressure`/`missing-load-shedding` routed through the gap-finder's judgment path (Tier-B
    `needs-review`) and refuted when the mechanism already fires in scope — the same shared-signature
    seam, so no drift.
  - **LLM findings narrative** (`sre_kb/reporting/narrative.py`, #41) — the engine emits a closed-world
    brief and grounds Copilot's returned prose against the digest: a `Kind/name` citation that doesn't
    resolve to a run artifact is flagged ungrounded, so a hallucinated risk can't pose as a finding.
    Advisory, `needs-review`, never gates (CLI `findings-narrative`).
  - The `AGENTS.md`-hijack + app-name-polyglot defenses are pinned by **named regression fixtures**
    (`tests/test_injection_regression.py`, #38) — the fence + `_mm()`/`_inline()` sanitizers existed;
    the named fixtures lock them against regression.
- **Infra — full scan/publish credential split** (§9.3 #5): the no-credential scan role **landed**
  (read-only `sre-target-scan` agent); the scoped publish role + CI wiring remain. Becomes a real
  safety bug the moment we publish live.
