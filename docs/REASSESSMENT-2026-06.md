# Reassessment & Next Steps — `sre-design` ↔ `resiliency-skills` (2026-06-06; deep review 2026-06-07)

> **Historical snapshot.** This is a dated reassessment captured *before* the Phase 4 gap-finder
> spike landed; its "Phase 4 is the make-or-break decision" framing has since been acted on. For
> current implementation status, see [`HYBRID-PLAN.md`](HYBRID-PLAN.md) §8 (the live tracker).

> **Why this doc exists.** Before resuming feature work we re-audited both repos *from source at
> their current `main`* and re-checked whether the merge/hybrid rationale in
> [`HYBRID-PLAN.md`](HYBRID-PLAN.md) still holds. It does — and a deeper second round ran **both
> engines end-to-end**, which confirmed the strategic frame and surfaced (and fixed) one real
> correctness bug. This doc is self-contained.
>
> **Rounds.**
> - *Round 1 (2026-06-06)* — static source audit. `sre-design` @ `ad7c8f5` (post-PR#6/CI);
>   `resiliency-skills` @ `e415166`, engine tests passing.
> - *Round 2 (2026-06-07)* — **deep three-pass review** (inventory → correctness/grounding →
>   synthesis), all three lenses (SDE/SRE/architect), with **both engines executed**.
>   `sre-design` re-run on branch `docs/reassessment-2026-06` (**166 tests**); `resiliency-skills`
>   re-cloned @ `00b3071` (PR#14, **62 engine tests** passing).
>
> Every claim was verified at a file/line or by running the code, not from a README.

---

## 1. Verdict (TL;DR)

1. **Our implementation matches its self-report — and is now *ahead* of the docs.** Every
   `HYBRID-PLAN.md` §8 "✅" claim is confirmed in code; **166 tests pass**. **Phase 3 (the Copilot
   challenge loop) is built and exercised end-to-end** — worklist → verdicts → `challenge-apply`
   monotonic re-gate — contrary to the docs' former "not started." Only the *in-process*
   `LLMChallenger` is dormant (superseded by the worklist; the engine never calls a model).
   Phases 4–5 remain not started. *(DESIGN/HYBRID-PLAN reconciled 2026-06-07.)*
2. **The hybrid plan's characterization of `resiliency-skills` still holds** at their current
   `main` (`00b3071`) — with the §4 corrections below. Their recent batches (A/B/D/E) **added
   rigor, not grounding**: a deterministic severity floor, engine-enforced clobber protection,
   honest fail-closed gates. The "broad but ungrounded" premise is, if anything, *stronger*.
3. **The frame stays "one-directional lift + bridge," not "reunite two halves."**
   `resiliency-skills` is deliberately diverging from deterministic / AST / file:line grounding;
   their roadmap + docs say so. They will not meet us in the middle.
4. **Our core bet is more differentiated than ever — and running both engines proved why.** Ours
   emits byte-grounded, verifiable claims and its challenge loop **caught a wrong-signal alert**;
   theirs rendered an unchecked/garbage query into a "deliverable" rule and validated a
   substanceless artifact. The grounded spine is the moat. It is correct *only if we commit to
   Phase 4* (the fenced Tier-B gap-finder) — without it we ship a narrow Java/.NET tool and "just
   extend `resiliency-skills`" becomes the rational alternative. **Phase 4 remains the make-or-break
   decision.**

---

## 2. Round 2 — deep three-pass review (2026-06-07)

**Method.** Three depth passes over both repos, all three lenses throughout: (1) inventory &
structure; (2) correctness & evidence-grounding — *both engines executed on sample inputs*;
(3) synthesis & head-to-head.

### 2.1 What running the engines proved

**`sre-design`** — `sre-kb run --to-stage validate` on `sample-spring-pcf`: **27 facts → 22
artifacts (19 verified, 3 needs-review)**. Generated artifacts carry real grounding —
`evidence[].path` + `lines.start/end` + `excerptHash: sha256:…` + `source_tier: ast`, re-derived
and rejected on mismatch. The Phase 3 loop ran to completion: `challenge-worklist` emitted 3
judgment-call claims (each with its untrusted excerpts injection-fenced); a verdicts file re-gated
via `challenge-apply`, which **downgraded the buggy latency alert `verified → needs-review`**
(monotonic, downgrade-only).

**`resiliency-skills`** — `latent-sre assemble examples/golden`: produced a complete **25-file
`SRE-<service>` tree** (catalog-info, metadata, slos, runbooks, dashboards, and **5 rendered alert
backends** — prometheus/grafana/splunk/wavefront/appdynamics, + a ThousandEyes proposal). Two gate
weaknesses reproduced **live**: a `spec: {}` Resiliency doc returns `validate: ok` (substance is
not gated), and a deliberately bogus PromQL string rendered **verbatim** into a deliverable
Prometheus rule (`signal.query` is passed through unchecked). A grep of the assembled output for
any line-level grounding field returned nothing — coarse, commit-level provenance by construction.

### 2.2 Bug found and fixed — a latency SLO burned on the wrong signal

The engine scaffolded `Alert/create-order-latency-burn-rate` (sloRef → a `sli: latency`,
p99 ≤ 800ms objective) but the burn-rate expr measured **`outcome!="SUCCESS"` (error rate)**,
ignoring the latency histogram its own evidence cited (`application.yml:30`,
`http.server.requests: …,800ms`). A latency SLO was alerted on availability. **Fixed**
(`synth/scaffold.py`): the derivation now branches on the objective's SLI — a latency objective
burns on the fraction of requests slower than its threshold (`…_bucket{le="0.8"}`); availability
objectives keep the error-ratio burn; a regression test asserts the latency expr uses the bucket
and never `outcome!="SUCCESS"`. Notably, the **challenge loop independently flagged this same alert
`unsupported`** — the adversarial oracle earning its keep.

### 2.3 Head-to-head scorecard

| Axis | `sre-design` | `resiliency-skills` | Edge |
|---|---|---|---|
| Grounding fidelity | `path:line:excerptHash`, re-derived | none by construction (repo/commit/skill) | **sre-design (decisive)** |
| Trust / verification | monotonic gates + status-aware crossref + challenge loop | schema-shape only; facts LLM-trusted | **sre-design** |
| Substance gating | `expr:{}` validates | `spec:{}` validates | tie — both weak |
| Output safety | exprs derived deterministically (one bug, now fixed + caught) | bogus query rendered verbatim | **sre-design** |
| Coverage breadth | logging-only collection; exprs emitted as strings | 5 rendered alert backends + Grafana JSON + full repo | **resiliency-skills (decisive)** |
| Security posture | fence-neutralized worklist, token-out-of-argv, publish allowlist | sandboxed Jinja, two secret engines, role docs | near tie |
| Supply chain | tag-pinned, floor-pinned deps, no Renovate | tag-pinned **+** `--require-hashes` + Renovate digest-pin | **resiliency-skills** |
| Code / test rigor | 166 tests, layered validation, real AST | 62 tests, simpler engine | sre-design (depth) / rs (simplicity) |

---

## 3. What we verified — `sre-design`

All §8 claims **CONFIRMED** in code (cited file:line throughout):

- **Phase 0** trust tiers: `Evidence.source_tier` (model + optional schema enum),
  `ScanContext.evidence(..., *, source_tier=)`, runtime-checkable `CollectorProtocol`, per-artifact
  `tier` + `by_tier` roll-up.
- **Phase 1** hardening (code-side): non-escapable fence (`synth/context_pack.py`), sanitized
  renderers (`render/copilot.py`), publish allowlist + token-out-of-argv (`publish/forge/github.py`),
  redact + secret gate (`security/secret_scan.py`), fan-out cap.
- **Phase 2** status-aware spine: crossref fixpoint downgrade, provenance path confinement
  (`is_relative_to`), status-aware readiness.
- **Phase 3** challenge loop: deterministic `GroundingChallenger` wired in the orchestrator;
  `build_worklist` → `challenge-worklist` → Copilot verdicts → `challenge-apply` monotonic re-gate;
  §7.3 adversarial-LLM corpus as the regression harness. **Built and exercised live (§2).**
- **§7.1–7.6** enhancements: tier-conflict findings, tier-aware guardrails, adversarial-LLM corpus,
  shared `signatures.rederive()`, trust-tier surfacing, schema governance (18/18
  `additionalProperties:false`, `ownership` enum, `unverifiedAgainstLive`, golden corpus).

**Caveats the audit surfaced:**

- **(A) Phase 3 honored the no-LLM invariant — resolved.** The Round-1 worry ("'wire `LLMChallenger`
  to a live oracle' would call a model") is moot: the shipped Phase 3 *is* the Copilot
  `challenge-apply` loop. The orchestrator runs `GroundingChallenger()` (deterministic); the
  in-process `LLMChallenger` stays a dormant hook returning *indeterminate* offline. The founding
  constraint (*Copilot is the only LLM; the engine never calls a model*) holds.
- **(B) Much Phase-4 scaffolding is still dormant.** §7.1 tier-conflict findings, `signatures.rederive`,
  and the `source_tier="llm"` plumbing are coded and unit-tested but **cannot fire today** — they key
  on `gap.*` facts that only a Phase-4 Tier-B collector produces. Phases 0–2 + §7 are, honestly, *the
  harness for a Tier-B producer that does not yet exist.* The first real end-user value unlock is Phase 4.
- **(C) Shared weak gate.** Like `resiliency-skills`, our schemas gate shape but not substance
  (`Alert.expr: {}` validates). A substance gate (reject empty `expr`/objective-without-target to
  needs-review) is a cheap, high-value follow-up.

---

## 4. What we verified — `resiliency-skills` (their `main` @ `00b3071`)

Their architecture today: a **scan role** (Copilot skills, an LLM, holding *no* credential) reads
the untrusted repo and emits *neutral* YAML (field shapes, never values) to `.sre-scan/<service>/`;
a deterministic **publish role** engine (`latent-sre`, in CI) renders those to per-tool configs,
validates against vendored JSON Schemas, runs a fail-closed secret gate, scaffolds a hardened
`SRE-<service>` repo, and (credentialed step only) opens the PR.

**The plan's premises — all still CONFIRMED:**

| Premise (from `HYBRID-PLAN.md`) | Status @ `00b3071` |
|---|---|
| "Thin skills, fat config"; extraction is LLM-driven | ✅ engine does deterministic transforms only; no LLM client in deps |
| Backed by a thin signature set; no AST extractor | ✅ signatures are advisory hints for the LLM, not a standalone detector |
| **No file:line evidence**; provenance is `repo/commit/scanDate/skill` | ✅ confirmed live (assembled-output grep empty) — see §4 note 1 |
| Schemas **permissive on substance** (`spec:{}` validates) | ✅ reproduced live (`validate: ok`) |
| Hardened: no-cred scan, `needs-human-review` const, sandboxed Jinja, `json.dumps` dashboards, fail-closed redact + 2nd gate, fan-out cap, name sanitization | ✅ all confirmed; recent batches strengthened these |
| `examples/malicious/` injection-containment fixtures | ✅ present + render/path-traversal tests |

**Recent movement since `e415166` (all *reinforces* the plan, none invalidates it):**
- **Batch A** (`make the gates honest`) — `validate` no longer aborts on one bad file; redact fixed
  fail-OPEN → fail-CLOSED on non-UTF-8.
- **Batch B** (`wire the missing guarantees`) — clobber-protection moved from agent prose **into the
  engine** (`.sre/manifest.yaml`); apiVersion gate made load-bearing.
- **Batch D** (`deepen the reliability model`) — **deterministic severity floor from `Criticality.tier`**
  (paging no longer depends on LLM consistency); structured resiliency gaps. The most substantive gain.
- **Batch E** (`architecture hygiene`) — central `registry.py`; versioned schema `$id`; CODEOWNERS
  sentinel fail-closed.
- Earlier `ac26bad` fixed a real **path-traversal**; the PyPI release workflow was removed (they
  distribute internally / offline-wheel — relevant to us, §6).

**New weak spots found by running it:**
- `signal.query` is rendered **verbatim** — a hallucinated/garbage PromQL ships as a "deliverable" rule.
- Substanceless artifacts validate (shared with us — §3C).

---

## 5. Corrections to `HYBRID-PLAN.md` (drift)

1. **Their `AlertIntent` carries an optional `metadata.source.{repo,commit,path}`** — the only schema
   with a `path`. It has **no `line`**, is **unenforced** (not `required`), and is **read by no
   renderer** (a dead field). So "no file:line grounding" holds; "no source field anywhere" is too strong.
2. **"`RunbookSpec` requires only `title`" is misleading.** Substance is permissive, but every schema's
   **root** mandates the full governance block (provenance/ownership/confidence/needs-human-review).
   The *envelope* is strict — a point in their favour.
3. **Their GitHub Actions are NOT SHA-pinned** (`@v4`/`@v5`; digest-pinning delegated to Renovate's
   first run). A gap to close **ourselves**, not lift. *(Same gap on our side — §6.)*
4. **~~Our `HYBRID-PLAN.md` §4 weaknesses are stale~~ — FIXED 2026-06-07.** All four (textual fence,
   token-in-argv + no allowlist, non-status-aware gates, no path confinement) are implemented; §4 now
   reads as "closed in Phase 1/2," and `DESIGN.md`'s "P3/deferred" language for the challenge pass +
   secret gate was corrected.

---

## 6. The strategic shift: divergence, not convergence

`HYBRID-PLAN.md` framed the two repos as "two halves of one lineage to **reunite**." The evidence
says otherwise: **`resiliency-skills` has made an explicit, documented commitment to *not* do what we
do.** LLM does inference; the engine does deterministic *transforms only*; signatures are *advisory
hints for the LLM*; provenance is intentionally commit-level. No doc proposes adding AST extraction,
file:line grounding, or deterministic detectors. Batches A–E doubled down on rigor *around* that
ungrounded core, not on grounding.

Three consequences:
- **(1) Our byte-grounding is uniquely ours.** They *ceded* the deterministic/verifiable-claim ground
  on purpose. Differentiation went **up** — and Round 2 showed the payoff (the challenge loop caught a
  wrong-signal alert their model could not mechanically detect).
- **(2) The hybrid is one-directional.** We **lift** their hardening + breadth; we **build** the Tier-B
  bridge ourselves. There is no "merge back" — resource it as a one-way absorption. **Do not merge the
  repos**; a merge would dilute the grounding thesis.
- **(3) The highest-leverage lift is in plain sight:** their Copilot skills *are* the Tier-B
  pointer-generators Phase 4 needs, and their `engine/templates/adapters/` already covers **all our
  target backends** (splunk, prometheus, grafana, appdynamics, wavefront, thousandeyes). Phase 4 and
  Phase 5 are substantially *lift*, not *invent*.

---

## 7. Convergent gaps to close (independent of the hybrid)

- **SHA-pin our CI actions.** `.github/workflows/ci.yml` uses `@v4`/`@v5` tags — the same gap
  `resiliency-skills` has. Pin to digests (or adopt Renovate `pinDigests`) and hash-pin deps.
- **Offline-wheel distribution.** Their `scripts/build-offline.sh` + "no public PyPI" decision is
  directly relevant to our on-prem/PCF/air-gapped target. Plan engine distribution the same way.
- **Optional second secret gate** (`detect-secrets`) alongside our redact + gate (defense-in-depth).
- **Substance gate** — reject empty `expr` / objective-without-target to needs-review (§3C).
- ~~Doc hygiene: fix `HYBRID-PLAN.md` §4 + refresh `DESIGN.md` "P3/deferred".~~ **Done 2026-06-07.**

---

## 8. Prioritized next steps

**Done this round (2026-06-07):**
- [x] **Phase 3 ratified as the Copilot `challenge-apply` loop** — confirmed built + exercised; no
      engine LLM client. The "no external LLM API" invariant holds.
- [x] **Latency burn-rate Alert bug fixed** (+ regression test) — §2.2.
- [x] **Docs reconciled** — DESIGN/HYBRID-PLAN Phase 3 status + stale §4/§8.

**P0 — the open keystone decision:**
- [ ] **Commit to Phase 4 (Tier-B gap-finder), yes/no?** (see §1.4). If *no*, re-scope explicitly: we
      are a deep Java/.NET correctness tool — decide whether that's the product vs. extending
      `resiliency-skills` for breadth.

**P1 — highest-leverage build (assumes Phase 4 = yes):**
- [ ] **First Tier-B collector: `assess-resiliency` in gap-mode** (`HYBRID-PLAN.md` §7.10). Reuse their
      `assess-resiliency` `SKILL.md`, adapt it to emit `(category, target, excerpt)` pointers; the
      engine locates → `path:line:hash` → re-derives via `signatures.rederive()` → lands `needs-review`,
      never auto-verify. **This single slice also activates the dormant §7.1 / §7.2 we already built.**
- [ ] **Recall eval fixture** (dual of the adversarial corpus): plant *known* gaps; assert the
      gap-finder surfaces them. Without it we can't tell signal from noise.

**P2 — hardening (independent, parallel):**
- [ ] SHA-pin CI actions + hash-pin deps; offline-wheel build; optional `detect-secrets` second gate;
      substance gate (§3C).
- [ ] Full **scan/publish credential split** (the one Phase-1 item still open — deployment/infra,
      scope separately).

**P3 — breadth (independent, high user-visible value, low LLM-trust risk):**
- [ ] **Render-adapter breadth (Phase 5):** generalize `render/` to neutral-intent → adapter and **lift
      their `engine/templates/adapters/*.j2`** for AppDynamics + Wavefront + ThousandEyes (+ reconcile
      Splunk/Prometheus/Grafana). Written for our exact backends.

**Sequencing:** P0 gates everything. P1 is the critical path (it's the only thing that proves the
design); P2 and P3 can proceed in parallel and are mostly lift-from-`resiliency-skills`.
