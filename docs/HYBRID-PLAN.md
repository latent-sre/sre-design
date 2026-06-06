# sre-design ↔ resiliency-skills: deep comparison, findings, and a hybrid plan

A source-level comparison of this repo (`sre-design` / the `sre-kb` engine) with
[`latent-sre/resiliency-skills`](https://github.com/latent-sre/resiliency-skills)
(the `latent-sre` engine + Copilot skill suite), the concrete weaknesses found in each,
and a phased plan to combine their strengths.

> **Provenance of this doc.** Both repos were read end-to-end from source (this one locally;
> `resiliency-skills` from a fresh clone of `main`). Every load-bearing claim below was
> verified at a named file/line or by executing the code — not taken from a README. Where a
> finding turned out to encode *tested intent* rather than a bug, that is called out.

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

### `sre-design` — weaknesses noted (not yet fixed; tracked for the hybrid)

- **Injection fence is textual and breakable** (`synth/context_pack.py:40`): the
  `<<<UNTRUSTED …>>> … <<<END UNTRUSTED>>>` delimiters and the path field are unescaped, so a
  hostile source file can close the fence early and inject instructions into the "trusted"
  region. The architectural defense in `resiliency-skills` is strictly stronger.
- **Publish path** (`publish/forge/github.py:98`): the token is embedded in the remote URL and
  passed as a `git` argv (visible to `ps`); `open_pr` has no target-repo allowlist (relies
  wholly on the ambient token's scope).
- **Gates not status-aware**: `crossref.py` resolves a reference if *any* artifact with that
  name exists, regardless of whether it is `verified`/`rejected`; `readiness` counts artifacts
  by kind, not status — a "verified" graph can cite unverified artifacts and grade "A".
- **`provenance.py:28`** has no path-confinement (`root / path` with no `is_relative_to` check) —
  harmless for engine output (always in-root) but bites edited / future LLM-sourced artifacts.
- **`DESIGN.md` is internally stale**: its header says the challenge pass and secret gate are
  built (they are — verified), while its body still says "P3 / deferred". Trust the code.

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
| **0. Fact contract & trust tiers** | Add `source_tier: ast\|llm` to `Fact`/`Evidence`; a `CollectorProtocol` both tiers satisfy. No behavior change. | Foundation. |
| **1. Adopt `resiliency-skills`' hardening wholesale** | Architectural scan/publish split (no-credential scan role; scoped publish credential), sandboxed/`json.dumps` renderers, `redact` + second gate, fan-out cap, `needs-human-review` const. | This *is* `sre-design`'s own deferred roadmap. Closes the textual-fence and publish-path weaknesses **before** any LLM breadth is added. |
| **2. Make the trust spine status-aware** | Fix `crossref`/`readiness`/gating to require `verified` referents; confine provenance paths (`is_relative_to`). | Or Tier-B facts will silently inflate "verified" graphs. |
| **3. Wire `LLMChallenger` to a live oracle** | Real adjudication for judgment-call claims. | Prerequisite for Tier-B, not polish — deterministic grounding is circular for LLM claims. |
| **4. LLM collectors as pointer-generators** | `collectors/llm/`; clone `sre-flow-analysis` into the granular skill set; engine re-confirms each pointer (§ contract). | The breadth payoff, now safely fenced. |
| **5. Render-adapter breadth** | Generalize `render/` to neutral-intent → adapter; add Wavefront/AppDynamics. | Independent; can run in parallel. |

Phases 0→1→2 are the trust/security spine and are low-risk extensions of existing code; they land
first. Phase 4 is the only heavy lift and the only new LLM-integration risk.

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
