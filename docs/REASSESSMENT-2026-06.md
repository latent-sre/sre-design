# Reassessment & Next Steps — `sre-design` ↔ `resiliency-skills` (2026-06-06)

> **Why this doc exists.** Before resuming feature work, we re-audited both repos *from
> source at their current `main`* and re-checked whether the merge/hybrid rationale in
> [`HYBRID-PLAN.md`](HYBRID-PLAN.md) still holds. It does — but the *strategic frame* has
> shifted, and that changes what we should build next. This doc is self-contained so a
> fresh chat can pick up and execute without re-reading the 33 KB plan.
>
> **Provenance.** `sre-design` audited at `main` = `ad7c8f5` (post-PR#6/CI). `resiliency-skills`
> audited at `main` = `e415166`, fresh clone, all 41 of their engine tests passing. Every
> claim below was verified at a file/line or by running the code, not from a README.

---

## 1. Verdict (TL;DR)

1. **Our implementation matches its own self-report.** Every `HYBRID-PLAN.md` §8 "✅" claim is
   confirmed in code; **166 tests pass**; Phases 3–5 are genuinely not started.
2. **The hybrid plan's characterization of `resiliency-skills` still holds** against their
   current `main` — with three minor corrections (§4 below). Their recent commits *strengthened*
   the security posture we planned to lift; none changed the premises.
3. **The frame must change from "reunite two halves" to "one-directional lift + bridge."**
   `resiliency-skills` is now *deliberately diverging away* from deterministic / AST / file:line
   grounding (their roadmap + docs say so explicitly). They will not meet us in the middle.
4. **Our core bet is therefore *more* differentiated than when the plan was written — but it is
   correct *only if we commit to Phase 4* (the fenced Tier-B gap-finder).** Without Phase 4 we
   ship a narrower tool than their polyglot breadth (Java/.NET-only, high-precision/low-recall),
   and "just extend `resiliency-skills`" becomes the rational alternative. **Phase 4 is the
   decision that makes or breaks the whole design.**

---

## 2. What we verified — `sre-design` (our `main`)

All §8 claims **CONFIRMED** in code (audit cited file:line throughout):

- **Phase 0** trust tiers: `Evidence.source_tier` (model + optional schema enum), `ScanContext.evidence(..., *, source_tier=)`, runtime-checkable `CollectorProtocol`, per-artifact `tier` + `by_tier` roll-up.
- **Phase 1** hardening (code-side): non-escapable fence (`synth/context_pack.py`), sanitized renderers (`render/copilot.py`), publish allowlist + token-out-of-argv (`publish/forge/github.py`), redact + secret gate (`security/secret_scan.py`), fan-out cap.
- **Phase 2** status-aware spine: crossref fixpoint downgrade, provenance path confinement (`is_relative_to`), status-aware readiness.
- **§7.1–7.6** enhancements: tier-conflict findings, tier-aware guardrails, adversarial-LLM corpus (5 fixtures, asserts the deterministic grounding gate downgrades/`rejects` planted claims), shared `signatures.rederive()`, trust-tier surfacing, schema governance (18/18 `additionalProperties:false`, `ownership` enum, `unverifiedAgainstLive`, golden corpus).

**Two honest caveats the audit surfaced:**

- **(A) Phase 3 "live oracle" collides with our own invariant.** `DESIGN.md` is emphatic:
  *Copilot is the only approved LLM; the engine never calls a model; no external LLM API anywhere.*
  In code today that holds — the orchestrator runs `GroundingChallenger()` (deterministic), and
  `LLMChallenger.adjudicate()` returns *"indeterminate; deferred to human"* whenever `client=None`
  (which is everywhere outside tests). So **"wire `LLMChallenger` to a live oracle" must mean the
  Copilot `challenge-apply` loop, not an engine-side API client** — otherwise it breaks the design's
  founding constraint. This needs to be stated explicitly before anyone implements Phase 3.
- **(B) Several "landed ✅" items are dormant scaffolding.** §7.1 tier-conflict findings is coded and
  unit-tested but **cannot fire today** — it keys on `gap.*` facts that only a Phase-4 Tier-B
  collector produces. Phases 0–2 + §7 are, honestly, *the harness for a Tier-B producer that does
  not yet exist.* The first real end-user value unlock is Phase 4.

---

## 3. What we verified — `resiliency-skills` (their `main` @ `e415166`)

Their architecture today: a **scan role** (18 GitHub Copilot skills, an LLM, holding *no*
credential) reads the untrusted repo and emits *neutral* YAML (field shapes, never values) to
`.sre-scan/<service>/`; a deterministic **publish role** engine (`latent-sre`, in CI) renders
those to per-tool configs, validates against vendored JSON Schemas, runs a fail-closed secret
gate, scaffolds a hardened `SRE-<service>` repo, and (credentialed step only) opens the PR. A
6-phase pipeline (`discover→classify→map→assess→generate→publish`) drives the 18 skills.

**The plan's premises — all still CONFIRMED:**

| Premise (from `HYBRID-PLAN.md`) | Status @ `e415166` |
|---|---|
| "Thin skills, fat config"; extraction is LLM-driven | ✅ 18 `SKILL.md`; engine does deterministic transforms only |
| Backed by only **8 signatures** (5 framework, 3 messaging, 0 datastore/infra/observability) | ✅ exactly 8 in `lib/signatures/` |
| **No file:line evidence**; provenance is `repo/commit/scanDate/skill` | ✅ (one nuance — see §4) |
| Schemas **permissive on substance** (empty `patterns`+`gaps` validate) | ✅ (one nuance — see §4) |
| Hardened: no-cred scan, `needs-human-review: const true` (×17), sandboxed Jinja, `json.dumps` dashboards, fail-closed redact + 2nd gate, fan-out cap, name sanitization, self-defending generated repo | ✅ all confirmed; **recent bugfixes strengthened these** |
| `examples/malicious/` injection-containment fixtures | ✅ 3 fixtures + render/path-traversal tests |

**Recent movement (all *reinforces* the plan, none invalidates it):**
- `ac26bad` fixed 6 engine bugs — incl. a **real path-traversal** (untrusted name written before
  validation) and two fail-closed-redact gaps. Their hardening is now *stronger* than when we wrote the plan.
- `173a9b5` **removed the PyPI release workflow** → they deliberately distribute *internally /
  offline-wheel*, not via public PyPI (relevant to us — see §6).
- PR5/PR6 added lockfiles, second secret gate, Renovate, the pipeline + `plan` orchestration.

---

## 4. Corrections to `HYBRID-PLAN.md` (drift to fix)

1. **Their `AlertIntent` *does* carry an optional `metadata.source.{repo,commit,path}`** — the only
   schema with a `path`. It has **no `line`** and is **unenforced** (not in `required`), so the spirit
   ("no file:line grounding") holds, but "no source field anywhere" is too strong.
2. **"`RunbookSpec` requires only `title`" is misleading.** `title` is the only requirement *inside
   `spec`*, but every schema's **root** mandates the full 8-field governance block
   (`apiVersion, kind, service, spec, provenance, ownership, confidence, needs-human-review`). The
   *substance* is permissive; the *envelope* is strict. (This is actually a point in their favour.)
3. **Their GitHub Actions are NOT SHA-pinned** (the plan implied supply-chain pinning was done).
   They use `@v4`/`@v5` tags and *delegate* digest-pinning to Renovate's first run (a deliberate
   "a fabricated SHA is worse than a tag" call). **So this is a gap to close ourselves, not lift.**
4. **Our own `HYBRID-PLAN.md` §4 weaknesses are stale** — all four (textual fence, token-in-argv +
   no allowlist, non-status-aware gates, no path confinement) are now **fixed**; that section reads
   as pre-implementation. `DESIGN.md` still calls the challenge pass + secret gate "P3/deferred"
   though both are built. (Doc-only; trust the code.)

---

## 5. The strategic shift: divergence, not convergence

`HYBRID-PLAN.md` framed the two repos as "two halves of one lineage to **reunite**." The current
evidence says otherwise: **`resiliency-skills` has made an explicit, documented commitment to *not*
do what we do.** Their `docs/roadmap.md`, `docs/versioning.md`, `docs/alert-intent-model.md` and
`__init__.py` all state: LLM does inference, the engine does deterministic *transforms only*;
signatures are *advisory hints for the LLM*, not a standalone extractor; provenance is intentionally
commit-level. **No doc proposes adding AST extraction, file:line grounding, or deterministic
detectors.** They are doubling down on thin-skills + governance-gate + neutral-artifacts.

Three consequences:

- **(1) Our byte-grounding is now uniquely ours.** They *ceded* the deterministic/verifiable-claim
  ground on purpose. If tractable human review and false-positive/false-negative bracketing are
  valuable (they are), we are the only ones building it. Differentiation went **up**.
- **(2) The hybrid is one-directional.** We **lift** their hardening; we **build** the Tier-B bridge
  ourselves. There is no "merge back" — plan and resource it as a one-way absorption.
- **(3) The highest-leverage opportunity is hiding in plain sight: their 18 Copilot skills *are* the
  Tier-B pointer-generators Phase 4 needs**, and their `engine/templates/adapters/` already covers
  **all five of our target backends** (`splunk`, `prometheus`, `grafana`, `appdynamics`, `wavefront`,
  `thousandeyes`). Phase 4 and Phase 5 are both substantially *lift*, not *invent*.

---

## 6. Convergent gaps to close (independent of the hybrid)

- **SHA-pin our CI actions.** We just shipped `.github/workflows/ci.yml` with `@v4`/`@v5` tags —
  the *same* gap `resiliency-skills` has. Pin to digests (or adopt Renovate `pinDigests`).
- **Offline-wheel distribution.** Their `scripts/build-offline.sh` + "no public PyPI, internal
  mirror/air-gapped wheel" decision is **directly relevant to our on-prem/PCF/air-gapped target**.
  We should plan engine distribution the same way rather than assuming PyPI.
- **Optional second secret gate** (`detect-secrets`) alongside our redact + gate, mirroring their
  defense-in-depth.
- **Doc hygiene:** fix `HYBRID-PLAN.md` §4 (stale) + add a dated reassessment pointer; refresh
  `DESIGN.md`'s "P3/deferred" language for the challenge pass + secret gate (both built).

---

## 7. Prioritized next steps (for the new chat)

**P0 — decisions to make before coding:**
- [ ] **Commit to Phase 4 (Tier-B gap-finder), yes/no?** This is the keystone decision (see §1.4).
      If *no*, re-scope: we are a deep Java/.NET correctness tool, and we should explicitly decide
      whether that's the product vs. extending `resiliency-skills` for breadth.
- [ ] **Ratify Phase 3 = the Copilot `challenge-apply` loop** (not an engine LLM client), preserving
      "no external LLM API." (Recommended.)

**P1 — highest leverage build (assumes Phase 4 = yes):**
- [ ] **First Tier-B collector: `assess-resiliency` in gap-mode** (`HYBRID-PLAN.md` §7.10 worked
      example). Reuse their `assess-resiliency` `SKILL.md`, adapt it to emit `(category, target,
      excerpt)` pointers; the engine locates → `path:line:hash` → re-derives via
      `signatures.rederive()` → lands `needs-review`, never auto-verify. **This single slice also
      activates the dormant §7.1 (tier-conflict) and §7.2 (advisory guardrails) we already built.**
- [ ] **Recall eval fixture** (the dual of the adversarial corpus): plant *known* gaps (a client with
      a deliberately removed timeout); assert the gap-finder surfaces them. Without it we can't tell
      signal from noise.

**P2 — hardening (independent, can run in parallel):**
- [ ] SHA-pin CI actions; offline-wheel build; optional `detect-secrets` second gate.
- [ ] Full **scan/publish credential split** (the one Phase-1 item still open — it's deployment/infra,
      not a refactor; scope it separately).

**P3 — breadth (independent, high user-visible value, low LLM-trust risk):**
- [ ] **Render-adapter breadth (Phase 5):** generalize `render/` to neutral-intent → adapter and
      **lift their `engine/templates/adapters/*.j2`** for AppDynamics + Wavefront + ThousandEyes
      (+ reconcile Splunk/Prometheus/Grafana). They've already written these for our exact backends.

**Sequencing:** P0 gates everything. Then P1 is the critical path (it's the only thing that proves
the design); P2 and P3 can proceed in parallel and are mostly lift-from-`resiliency-skills`.
