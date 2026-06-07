# Review: `latent-sre/resiliency-skills` → `sre-design` (June 2026)

In-depth, three-pass review (master SDE · SRE · architect) of the **latest `resiliency-skills`
`main`** against **our `main`**, with lift-and-shift / refactor recommendations, a Tier-B skill
expansion plan, and LLM-enhancement ideas.

## Scope, method, and honesty caveats

- **What I compared.** `resiliency-skills` `main` at **`f99e028`** (29 commits) vs. our `main` at
  `fa484fe`. Our vendored skills are pinned at **`00b3071`** — i.e. `resiliency-skills` is only
  **one PR ahead** of our vendor point (`#15`, "Harden assemble/scaffold"). This is **not** a
  "we're far behind" situation; it is **two sibling designs of the same system** that diverged.
- **Access limitation (stated plainly).** I could **not** clone `resiliency-skills`: it is outside
  this session's repo scope (git proxy returns *"repository not authorized"*; the GitHub MCP is
  scoped to `latent-sre/sre-design`; the `list_repos`/`add_repo` escalation tools are not present in
  this session). I reconstructed it from the **public `github.com` / `raw.githubusercontent.com`
  pages via WebFetch** (README, `lib/`, `engine/`, `docs/`, `.github/skills/`, and the recent commit
  diffs). Fidelity is high for text/YAML/JSON-schema content; I did **not** run their test suite or
  read every engine line. To get a byte-exact diff later, add `latent-sre/resiliency-skills` to the
  session scope and I'll re-verify.
- **What I deliberately did not read**, per your instruction: `docs/HYBRID-PLAN.md`,
  `docs/PHASE-4-GAP-FINDER.md`, and the `REASSESSMENT-*` docs. These findings are therefore formed
  **independently**. Consequence: some recommendations may **overlap with items already on your
  roadmap**. I saw breadcrumbs in `DESIGN.md` / `registry.yaml` (e.g. "§9.6 adopted from
  resiliency-skills", "Round-3 R5 parameter-completeness gaps", Dashboard + Criticality already
  adopted) and have flagged "**already partial**" wherever I noticed one. **Post-review update:** I
  have now cross-checked every recommendation against those docs — see the **Addendum** at the end.
  Bottom line: an internal three-pass review (`REASSESSMENT-2026-06-07-round3.md`) independently
  reached nearly all the same structural conclusions, so most items here are already **done** or
  **tracked-open**; the net-new yield is **N1 (a real bug)** plus N2–N5.

## The relationship between the two repos

Both solve the **same problem**: scan a dev repo → build a validated SRE knowledge base → project it
into Copilot assets → open a PR into a company SRE repo. They differ in **center of gravity**:

| | **sre-design (ours)** | **resiliency-skills (theirs)** |
|---|---|---|
| Philosophy | Engine-first; AST extraction; **hard provenance** (`path:line:commit:excerptHash`) | **Thin skills, fat config, deterministic transforms** |
| Trust model | **Trust tiers** (Tier-A `ast` vs Tier-B `llm`); LLM is a fenced **pointer-generator** (locate→stamp→re-derive) | **Two roles, one boundary**: read-only scan agent emits neutral artifacts; CI publish role renders/validates/redacts |
| Validation | **5 layers** incl. an **adversarial challenge** pass (grounding + LLM hook), monotonic downgrade-only | schema-validate + fail-closed redact gate + governance `const` fields |
| Detection data | Deterministic **resilience-pattern signatures** (regex/AST) — *we lead* | Declarative **framework/messaging** signatures + a single **`taxonomy.yaml`** — *they lead* |
| Breadth | 3 skills (flow, gap-finder, criticality); 4 alert adapters | **18 skills**; **6 adapters** (+ThousandEyes, Grafana, OTel); Backstage; dashboards |
| Security boundary | Many controls, but credential split **deferred** | Scan/publish **never share a context** (explicit, central invariant) |

**Bottom line up front:** their strengths are exactly our deferred items (security role-boundary,
fat-config breadth, the secret gate, operational depth in alerts/jobs/messaging), and our strengths
(byte-grounded provenance, trust tiers, adversarial validation) are things they do not attempt. The
right move is **synthesis, not pivot**: keep our grounding moat, lift their breadth + boundary +
hardening, and re-sequence so the boundary lands **before** we widen the LLM surface.

---

## Pass 1 — Master SDE lens (engineering quality, correctness, maintainability)

**1.1 Secret-scan fail-open on non-UTF-8 files — a real correctness/security bug (P0).**
`security/secret_scan.py:62` (`_looks_text`) reads the first 2048 bytes and treats **any file
containing a NUL byte as binary → skipped entirely** by both `scan_tree` and `redact_tree`. A
UTF-16-encoded text file (ASCII content → interleaved `\x00`, e.g. a Windows `appsettings.json`,
a PowerShell profile, a UTF-16 `.env`) is therefore **never scanned and never redacted — a secret
in it passes our publish gate silently.** `errors="replace"` on the UTF-8 read can also corrupt a
secret so the regex misses it. `resiliency-skills` fixed exactly this in **Batch A**: a
`_decode_for_scan` that tries **UTF-8-sig → UTF-16(BOM) → UTF-8 → latin-1**, classifies binary as
**≥30 % control bytes** in the first 8 KB, and emits an explicit `unreadable` **finding** rather than
skipping. **Lift their decode logic.** Low effort, high value.

**1.2 A single controlled vocabulary (`taxonomy.yaml`).** Their `lib/taxonomy.yaml` is the one
source for every enum (artifact kinds, `resiliency.pattern`, `criticality.tier`,
`dataClassification`, `alerting.severity`, `sloWindows`, …); skills and schemas reference it, "kept
in lockstep with the schemas." We **scatter enums across ~28 JSON Schemas** with no single vocabulary
and a **vocabulary mismatch already exists** (our severity `critical/high/medium/low` vs their
`sev1/sev2/sev3`; our resilience concerns vs their pattern list). Recommendation: introduce
`lib/taxonomy.yaml` as the single vocabulary and add a test asserting schema enums stay consistent
with it (we already "generate canonical text from the schemas", so invert/augment that). Kills drift;
prerequisite for clean breadth.

**1.3 Declarative detection signatures (fat config) for breadth.** Their `lib/signatures/*.yaml`
detect tech stack + messaging via `anyOf` matchers (`file`+`contains`, `jsonHasDependency`,
`importContains`, `fileGlob`) across **Java, Node/Express, Python/FastAPI, Go, .NET** — *adding a
stack is data, not code*. Ours is per-language Python collectors (deeper, but each new stack is code).
**Synthesis:** use **declarative signatures for inventory/breadth** (tech-stack, dependencies,
messaging, datastores — incl. Node/Go that we lack) while **keeping AST for flow/resiliency
grounding** (our fidelity moat). Note their lib has **no** resilience-pattern signatures — that is
where *we* are ahead (`signatures.py`); we should not regress it.

**1.4 Resilience-signature coverage gaps (quick win, P1).** Our `signatures.py` covers
`circuit-breaker, fallback, timeout, retry, scheduled` — but **`bulkhead`, `rate-limit`, and
`idempotency` have no signature**, even though `gap_finder._INSTANCE_ANNOTATIONS` already lists
`@Bulkhead`/`@RateLimiter` and `_JUDGMENT_CATEGORIES` includes `missing-idempotency`. Their taxonomy
lists all three as first-class patterns. Add the three signatures (Resilience4j `@Bulkhead`/
`@RateLimiter`, Polly bulkhead/rate-limit, idempotency-key patterns). Small change, immediately
strengthens the gap-finder's refutation/confirmation probes.

**1.5 Central registry discipline.** Their **Batch E** added `registry.py`
(`ArtifactKind(kind, schema, dir, renderer)`) to replace ~6 duplicated kind→behavior mappings — a
miss in any one caused a silent failure. We already have `schemas/registry.yaml` (kind → schema /
collector / prompt / phase) as **data**, which is arguably better. Action item is an **audit**: make
sure `render/`, `synth/scaffold.py`, and `publish/` *dispatch off the registry* rather than carrying
their own kind-conditionals (their pain point). Add the missing facets (output dir, renderer) to our
registry if any dispatch is still hard-coded.

**1.6 Robustness items worth mirroring (Batch A/B + assemble-hardening).** Per-file parse isolation
(one bad YAML doesn't abort the tree); **exit-code discipline** (0 success / 1 gate-failure / 2 bad
invocation); **collision detection** (two artifacts → same path = fail closed); **render-output
validation** before write; `apiVersion`-too-new rejection. Audit our `cli.py`/`validation/` for the
same and close gaps.

**1.7 Adversarial test fixtures to lift.** Their `examples/malicious/` has three excellent fixtures:
a prompt-injection `README.md` (jailbreak + RCE + cred-exfil + integrity tampering), an **`AGENTS.md`
hijack** (proves the scanner ignores a target's agent file), and an **app-name polyglot**
`manifest.yml` (`evil"];}-->` `` `$(whoami)` ``) targeting Mermaid/JSON/shell. Our `render/diagrams.py`
`_mm()` already strips those metacharacters and our context fence is non-escapable — so we are likely
**defended but not regression-tested**. Lift the fixtures into `tests/fixtures/` and assert the
defenses hold.

---

## Pass 2 — Master SRE lens (operability, alerting quality, incident-readiness)

**2.1 Symptom-vs-cause alert classification (P1, high value / low cost).** Their alerts carry
**`class: symptom|cause`** — *symptom* = user-facing/SLO-linked → **page-eligible**; *cause* =
diagnostic → ticket-eligible. This is core Google-SRE doctrine ("page on symptoms"). We have no such
field. Add `class` to the `Alert` schema and thread it through the alert intent + severity floor so
only symptom alerts page. Immediate alert-quality improvement.

**2.2 Multi-window/multi-burn-rate completeness (P0–P1, verify then refine).** Their `sloWindows`
and AlertIntent `burnRate{shortWindow,longWindow,factor}` encode **both** a long and a **short**
window — fast `5m/1h @14.4`, slow `30m/6h @6`. Our `render/alerts.py` `BURN_WINDOWS` uses **only the
long windows** (`1h@14.4`, `6h@6`) and emits one condition each — so we lack the **short-window
confirmation** of the canonical multi-window/multi-burn-rate alert. Effect: our alerts fire on an
**hour-old** burn that may already be resolved (slow to reset) and are more false-positive-prone.
Recommendation: render the full MWMBR — *fast =* `(1h burn > 14.4·budget) AND (5m burn > 14.4·budget)`,
*slow =* `(6h > 6·budget) AND (30m > 6·budget)`. (Flagged "verify": this is inferred from one module.)

**2.3 `ObservabilityCoverage` as a first-class artifact (P1).** Their `assess-observability-coverage`
scores **metrics/logs/traces/synthetics** as `covered|partial|missing` with an **impact-ordered
`gaps[]`**. This is distinct from our PRR `ReadinessScore` (a grade): a coverage matrix that
prioritizes *instrumentation work*. We already extract logging/metrics/tracing facts, so this is a
cheap roll-up projection with high SRE value — and a natural new Tier-B/derived kind.

**2.4 Job reliability — silent-incident coverage (P1).** Their `map-jobs` captures `timeoutSeconds`,
**`concurrencyPolicy` (allow/forbid/replace)**, and `expectedDuration` — "an overlapping or hung cron
with no timeout is a classic silent incident." Our `ScheduledJob` has `idempotent/retrySafe/dedupeKey`
but not concurrency/timeout/duration. Extend the schema and add gap detection (job with no timeout;
no concurrency guard; no success signal). We already have a `scheduled` signature
(`@DisallowConcurrentExecution`) and an `undocumented-job` confirmation probe — extend them.

**2.5 Messaging resilience — poison-message / retry-storm coverage (P1).** Their `map-messaging`
captures **`dlq`, `maxRedelivery`, `ordering`, `idempotentConsumer`** and pairs them with
`assess-resiliency`. We have `Interface(async)` + `deliveryGuarantee` but not these. Add the fields +
gaps (consumer with redelivery but **no DLQ** and **non-idempotent** = poison-message risk). High SRE
value on Kafka/Rabbit estates.

**2.6 Load-bearing resilience params as gaps (P1, already partial).** Their `assess-resiliency`
treats a pattern *missing its parameters* as a gap (retry w/o `backoff`/`budget` = retry-storm;
timeout w/o `timeoutMs`; CB w/o thresholds). Our vendored `assess-resiliency.SKILL.md` already states
this, we have `resiliency_params.py`, and `registry.yaml` references "Round-3 R5 parameter-
completeness gaps" — so **partly there**. Action: confirm full deterministic coverage of
retry-without-backoff / timeout-present-without-value / CB-without-thresholds as **Tier-A** gaps.

**2.7 PCF operability depth (P2).** Their `map-pcf-application` records deploy **strategy**
(blue-green/rolling/canary/recreate), **autoscaler** `{min,max,metric}`, **log drains**, and
health-check `timeout/invocationTimeout` — feeding rollback steps and saturation alerts. Our
`Deployment` has instances/mem/routes/healthCheck. Extend the PCF facts (directly relevant to our
on-prem/PCF reality).

**2.8 Severity-floor calibration (note, not a clear win).** Their floor maps **tier0→sev1 AND
tier1→sev1** (both top), tier2→sev2, tier3→sev3; ours maps tier0→critical, **tier1→high**. Decide
deliberately whether tier1 should also floor to top severity. Calibration question for the taxonomy
work (2.1/1.2).

**2.9 New alert adapters (P1, breadth).** Their `render-adapters` ships **ThousandEyes** ("proposal-
only") and **Grafana** ("deliverable") templates we don't implement, plus OTel as a signal source.
ThousandEyes is in our DESIGN's target list but absent from `render/alerts.py`; Grafana dashboards are
the next increment our `dashboards.py` already anticipates. Add both adapters via the existing seam.

---

## Pass 3 — Master architect lens (boundaries, security architecture, evolvability, strategy)

**3.1 The two-role / never-share-a-context boundary — their best idea, our biggest gap (P0).**
They split **SCAN** (read-only Copilot; no terminal, network, or write credential; target = data)
from **PUBLISH** (CI; credential scoped *only* to `latent-sre/SRE-*`; deterministic). *"The agent that
reads untrusted code and the credential that can write never share a context."* We have many controls
(non-escapable fence, redact + secret gate, repo allowlist, token-out-of-argv) but `DESIGN.md`
explicitly **defers the scan/publish credential split**. We are close — the engine never calls an LLM
and publish is already a separate stage — so the lift is mostly **formalizing the invariant**: the
VS Code scan/enrich loop must never hold the publish token; publish runs only in CI with an SRE-*-
scoped credential; only schema-valid, value-free artifacts cross. This is the single most important
change for enterprise trust, and a **precondition** for safely scaling the LLM (Tier-B) surface.

**3.2 Self-validating generated repo: vendored schemas + pinned engine (P2).** Their `scaffold`/
`assemble` lays down an `SRE-<service>` repo that **ships its own copy of the schemas + engine version
and its own least-privilege CI**, so downstream validation is **decoupled from upstream drift**, with
a `CODEOWNERS` `REPLACE_ME__owning_team` sentinel that **fails CI closed** if unreplaced. We project
skills/catalog into the SRE repo but don't vendor schemas/pin the engine for the downstream repo's
self-validation. Adopt this — it makes a *living* KB safe at fleet scale.

**3.3 Living-KB clobber protection (P1).** Their `assemble` compares each file's normalized hash
against `.sre/manifest.yaml`; a human-diverged file is **never overwritten** — the new draft goes to
**`.proposed/`** — plus collision detection, orphan pruning, and corrupt-manifest tolerance. We open a
PR (human reviews the diff) but have no mechanism to **preserve human edits on re-publish**. For a KB
humans edit in the SRE repo, add manifest-based clobber protection + `.proposed/` routing (or
explicitly decide PR-review is the boundary and document it).

**3.4 Persist the neutral AlertIntent as the artifact (refactor).** Their **AlertIntent** is the
*persisted, reviewed* artifact; per-tool dialects are deterministic projections — so a human reviews
the intent **once**, not N dialects, and a new tool is a new template. We compute the intent
*transiently* in `alerts.py` and persist the rendered `expr`. Consider persisting the neutral intent
(signal/condition/burnRate/class/severity/renderTargets) as the artifact and rendering dialects as
projections. Cleaner evolvability; aligns with their `needs-human-review: const true` guarantee.

**3.5 Fan-out orchestration with human-confirm + granular resume (P2).** Their `plan` emits a
per-service `ScanPlan` (canonical 18-skill pipeline × fan-out) and **refuses to mass-create above a
cap** (`requiresHumanConfirm: true`, non-zero exit); `scan-state` resumes per **`(service, skill)`**.
We have a publish-time fan-out cap and an `estate` command, but no resumable multi-service *scan plan*.
Extend `estate` into a scan-plan/orchestration layer for monorepo fleets.

**3.6 Supply-chain & on-prem hardening (P2).** Their PR5 adds lockfiles + `--require-hashes`,
renovate SHA-pinning, an **independent OSS second secret scanner** (`detect-secrets`), an **offline
wheel bundler for air-gapped PCF**, and `SECURITY.md`. Our `DESIGN.md` defers supply-chain pinning.
The **offline wheel** is directly relevant to our on-prem/PCF reality; the **OSS second scanner** is
cheap defense-in-depth on top of fixing 1.1.

**3.7 Strategic verdict — synthesize, re-sequence; do not pivot.** Direction is sound. The only
"pivot" is **sequencing**: elevate the **security role-boundary (3.1)**, **fat-config breadth
(1.2/1.3)**, and **secret-gate hardening (1.1/3.6)** from "deferred" to "now", *before* expanding the
Tier-B skill suite — because more skills = more LLM/prompt-injection surface, which the boundary and
gate must contain first. Same destination, safer order.

---

## Tier-B skill expansion — feasibility and plan

**Does it work? Yes — proven twice.** Our model already vendors a `resiliency-skills` `SKILL.md` as
the **prompt half** and adds an engine **grounding half**: `assess-criticality-and-data → sre-criticality`
(+ `collectors/common/criticality.py`) and `assess-resiliency → sre-gap-finder`
(+ `collectors/llm/gap_finder.py`). The recipe is repeatable: **vendor SKILL.md → add a deterministic
probe/collector → add a schema + one `registry.yaml` row.** (Reminder per your note: this objective
review concludes the mechanism *works*; it did not bias the findings above.)

**But not every one of their 18 skills should be Tier-B.** Sort them by what the LLM actually adds:

- **Strong new Tier-B proposers** (LLM widens recall on judgment-heavy gaps; engine grounds): 
  `assess-observability-coverage`, `map-jobs`, `map-messaging`, `assess-logging`. These pair with the
  schema/field extensions in 2.3–2.5 and have clear deterministic probes (missing DLQ, hung-cron,
  absent correlation-id, signal coverage). **Recommended additions.**
- **Judgment-routed only** (no deterministic probe — `needs-review`, like our existing judgment
  categories): `generate-slos` (LLM *proposes* targets; engine never fabricates).
- **Better as Tier-A declarative collectors** (inventory/mapping — the LLM may *narrate* but must not
  *assert*): `assess-tech-stack`, `map-dependencies`, `map-architecture`, `map-infrastructure`,
  `map-api-contracts`, `map-delivery`, `map-pcf-application`. Implement via the declarative signatures
  of 1.3, not as LLM proposers.
- **Already derived kinds** (engine derives, Copilot enriches): `generate-alerts`,
  `generate-dashboards`, `generate-runbooks`.
- **Maps to publish/boundary work**: `publish-sre-repo` → our publish stage + 3.1.

**Recommended first batch of new Tier-B skills:** `sre-observability-coverage`, `sre-job-reliability`,
`sre-messaging-resiliency` (each: vendored SKILL.md + new signatures/probe + schema + registry row +
golden fixture + tests). This is the concrete answer to "add more skills based in Tier B."

---

## How LLM can further enhance our findings (within the fence)

Our discipline (LLM = grounded pointer-generator, never a fact source) is correct. Higher leverage
*without* breaking it:

1. **Activate the dormant `LLMChallenger` via the Copilot worklist.** `validation/challenge.py`
   already has the hook and a downgrade-only contract. Broaden `extract_review_claims` (alert
   appropriateness, runbook-step safety, SLO-target sanity, data-classification escalation) so the
   LLM adjudicates more judgment calls — still monotonic, still grounded. Highest-leverage, lowest-risk.
2. **More Tier-B recall via the new skills above** — each gives the LLM a structured lens to propose
   gaps the AST misses; the engine grounds/refutes.
3. **LLM-authored narrative over the `findings` digest** (clearly Tier-B/advisory): turn the ranked
   risk list into an incident-readiness narrative for humans — enhances *communication* of findings
   without polluting facts.
4. **Graduation/promotion workflow** (your README's next step): LLM proposes recurring gap categories;
   humans confirm; engine adds a deterministic probe → the category graduates Tier-B→Tier-A. The LLM
   accelerates *discovery of new deterministic rules*.
5. **Guardrail:** every added LLM lever widens the prompt-injection surface — 3.1 (role boundary),
   the non-escapable fence, and downgrade-only gating must hold. This is why 3.1 is sequenced first.

---

## Prioritized recommendations

| # | Recommendation | Lens | Effort | Value | Notes |
|---|---|---|---|---|---|
| P0-1 | Fix secret-scan fail-open (multi-encoding decode) | SDE/Sec | S | High | bug; lift `_decode_for_scan` (1.1) |
| P0-2 | Formalize scan/publish role-boundary invariant | Arch/Sec | M | High | prerequisite for LLM breadth (3.1) |
| P0-3 | Verify + complete multi-window/multi-burn-rate alerts | SRE | S–M | High | inferred; verify (2.2) |
| P1-1 | Alert `class: symptom\|cause` | SRE | S | High | page on symptoms (2.1) |
| P1-2 | Central `lib/taxonomy.yaml` + consistency test | SDE | M | High | also fixes severity vocab (1.2/2.8) |
| P1-3 | Declarative tech-stack/messaging/datastore signatures | SDE/Arch | M | High | breadth incl. Node/Go (1.3) |
| P1-4 | `bulkhead`/`rate-limit`/`idempotency` signatures | SDE/SRE | S | Med–High | quick win (1.4) |
| P1-5 | `ObservabilityCoverage` artifact + skill | SRE | M | High | new Tier-B (2.3) |
| P1-6 | Job reliability fields + gaps + skill | SRE | M | High | silent incidents (2.4) |
| P1-7 | Messaging resilience fields + gaps + skill | SRE | M | High | poison-message (2.5) |
| P1-8 | Hardened secret gate (entropy + uri-creds + jwt + OSS 2nd) | Sec | M | High | on top of P0-1 (3.6) |
| P1-9 | `assemble` clobber-protection (`.proposed/`+manifest) | SDE/SRE | M | Med–High | living KB (3.3) |
| P1-10 | ThousandEyes + Grafana adapters | SRE | S–M | Med | breadth (2.9) |
| P1-11 | Adversarial fixtures (AGENTS.md hijack, app-name polyglot) | SDE/Test | S | Med | regression-test defenses (1.7) |
| P2-1 | Self-validating generated repo (vendored schemas+engine) | Arch | M | Med–High | fleet scale (3.2) |
| P2-2 | Supply-chain hardening + offline PCF wheel | Arch | M | Med | on-prem (3.6) |
| P2-3 | Scan-plan fan-out + per-(service,skill) resume | Arch | M | Med | scale (3.5) |
| P2-4 | Persist neutral AlertIntent as the artifact | Arch | M | Med | evolvability (3.4) |
| P2-5 | `load-shed`/`backpressure` vocab + judgment Tier-B | SRE | S | Low–Med | (2.6) |

Effort: S ≈ hours, M ≈ a day or two. "Already partial" items: P1-6/P1-7 fields, the param-completeness
gaps (2.6), and the Dashboard/Criticality adoptions are partly in place.

---

## Addendum: reconciliation against the internal planning docs

After the initial review I cross-checked every recommendation against the previously-excluded docs
(`HYBRID-PLAN.md`, `PHASE-4-GAP-FINDER.md`, `REASSESSMENT-2026-06.md`,
`REASSESSMENT-2026-06-07-round3.md`). **Headline:** `REASSESSMENT-2026-06-07-round3.md` is itself an
independent three-pass (SDE→SRE→architect) review that pinned `resiliency-skills` @ `f99e028`, ran
both test suites (235/69), and **converged with this review on essentially every structural item** —
strong mutual validation. Consequently most recommendations here are already **done** or
**tracked-open**; a small set are **genuinely new**.

**Already implemented (this review confirms landed work — no action):**
- Severity floor by Criticality tier (§2.8) — `render/alerts.py:effective_severity` (round-3 **R2**).
- `Criticality` kind + `dataClassification` (PII/PCI) — `collectors/common/criticality.py` (**R1**).
- `assess-criticality-and-data` Tier-B skill — `.github/skills/sre-criticality/` (**R3**).
- Alert `class: symptom\|cause` + `signal` + structured `burnRate` + `renderTargets` **as schema
  fields** — `Alert.schema.json` (HYBRID-PLAN §9.6 #1). *But see N2 — the renderer doesn't use them.*
- `ScheduledJob` + concurrency — `collectors/java_spring/jobs.py`.
- Pattern-without-params gaps (§2.6) — `resiliency_params.py` (**R5**: CB-thresholds, retry-backoff;
  timeout-duration deferred).
- tier-conflict findings, tier-aware guardrails, shared `signatures.py`, the substance gate.

**Already tracked, still open (this review confirms a roadmap item):**
- `assess-observability-coverage` Tier-B skill **+ refutation probe** — round-3 **R6** = my **P1-5**.
- `map-messaging` DLQ/idempotency gaps — round-3 §5 "add later" = my **P1-7**.
- grafana + thousandeyes adapters — round-3 **R7** / §9.6 #2 = my **P1-10**.
- Clobber-protection manifest on publish (`.proposed/`) — round-3 **R4** = my **P1-9**.
- Supply-chain `--require-hashes` + Renovate digest-pin + `detect-secrets` second gate + offline
  wheel — round-3 **R8** / §9.6 #3 / REASSESSMENT-2026-06 = my **P1-8 (part) / P2-2**.
- Full scan/publish credential split — HYBRID-PLAN §9.3 #5 (deferred infra) = my **P0-2**.
- Resumable multi-service scan-plan — round-3 §4.3 "note for later" = my **P2-3**.

**Genuinely new — in no planning doc (the net-new yield):**
- **N1 — Secret-scan fail-open on non-UTF-8 (P0 bug).** `secret_scan._looks_text` skips any file
  containing a NUL byte, so a UTF-16 file is never scanned *or* redacted. **Reproduced live:** a
  planted `AKIA…` key in a UTF-16 file produced **zero findings** and **survived `redact_tree`**,
  while the identical UTF-8 file was caught. The planned `detect-secrets` second gate (R8) might mask
  it, but our own fail-closed gate is fail-open here today. Fix = multi-encoding decode (lift their
  Batch A `_decode_for_scan`). **The single most important new finding.**
- **N2 — Multi-window burn-rate is single-window in the renderer.** The AlertIntent *schema* carries
  `shortWindow`/`longWindow`, but `render/alerts.py` `BURN_WINDOWS` emits only the **long** window per
  rate (1h@14.4, 6h@6); `test_burn_rate_expr.py` confirms no short-window AND-condition. Canonical
  MWMBR ANDs long+short (1h&5m, 6h&30m) to cut false pages and reset fast. Verify + complete (SRE).
- **N3 — `bulkhead`/`rate-limit` signatures absent** (idempotency too). `signatures.py` has 5
  concerns; the gap-finder already references `@Bulkhead`/`@RateLimiter`. Quick win.
- **N4 — No central vocabulary; severity-vocab mismatch.** Round-3 keeps `signatures.py`
  (presence/absence) and explicitly does *not* adopt a unified enum vocabulary; `critical/high/
  medium/low` vs `sev1/sev2/sev3` is unreconciled. A `lib/taxonomy.yaml` + consistency test closes drift.
- **N5 — lower priority:** `load-shed`/`backpressure` vocab+probes; **declarative inventory
  signatures** as an alternative to the plan's LLM-for-breadth (a conscious choice on their side); an
  **LLM-authored narrative** over the `findings` digest; lifting the **`AGENTS.md`-hijack /
  app-name-polyglot** fixtures as regression tests (defenses exist via the fence + `_mm()`; named
  fixtures don't).

**Tier-B skill expansion — reconciled with the non-circular contract.** Round-3 §5 and this review's
Pass-3 agree: a Tier-B skill earns its place **only when paired with a deterministic probe or
consumer**. Of the four requested: `observability-coverage` is the clean next one (round-3 **R6**,
refutation probe against our `Observability` facts); `logging-posture` is best **folded into**
observability-coverage (logging is an input signal, not a separate artifact — avoids a redundant
skill); `messaging-resiliency` needs a confirmation probe (DLQ/idempotency vs messaging facts);
`job-reliability` extends the existing `ScheduledJob` + a concurrency/timeout confirmation probe.

**Net:** the plan is current and sound; this review corroborates it and adds **N1 (a real bug)** as
the headline, plus N2–N5.
