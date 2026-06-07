# Phase 4 — LLM gap-finder (spike)

The first **Tier-B (LLM) collector**, built as a spike on the primitives already in `main`
(`signatures.py`, `tiers.py`, `Evidence.source_tier`). It implements the recall mode of
HYBRID-PLAN **§7.9/§7.10**: Copilot proposes resiliency gaps the AST missed (e.g. a critical client
call with no timeout); the **engine** — never the LLM — locates each proposal, stamps it
`path:line:excerptHash`, and re-derives or *refutes* it deterministically. Nothing verifies on
proposal alone.

## The non-circular contract

The LLM is a **pointer-generator**, not a fact source:

1. It quotes the **verbatim excerpt** a gap lives at — never a line number.
2. The **engine locates** those bytes itself (`_locate`) and stamps the citation with
   `source_tier="llm"` — a quote it can't find verbatim is dropped (no fabricated citations).
3. The **engine re-derives** with the *shared* `signatures` library (§7.4), the same rule Tier-A
   keys off, so the two can't drift. For `missing-timeout`: there must be an outbound client call in
   scope **and** the `timeout` signature must fire **nowhere the engine checked** (the enclosing
   type + config files). If it fires, the gap is refuted and dropped — the LLM can't assert a gap
   that isn't there. The surviving artifact records the honest `checked:` list of places searched.

The LLM widens **recall**; the engine makes the assertion. This is the mirror of the challenge pass
(§7.3): challenge catches false positives ("is this claim grounded?"); the gap-finder catches false
negatives ("what true claim did we miss?").

## What it emits

A `ResiliencyGap` artifact (new kind; per-kind schema with `additionalProperties:false` + a
golden-corpus example). The tier depends on the probe class:

- Refutation-probe absence gaps land `status: needs-review`, `confidence: 0.5`,
  `provenanceMode: llm-asserted`, `unverifiedAgainstLive: true`, `spec.sourceTier: llm`, and the
  `checked:` honest-negative trail.
- Confirmation-probe gaps graduate when the deterministic rule fires at the pointer:
  `status: verified` if the normal gate passes, `provenanceMode: deterministic`,
  `spec.sourceTier: ast`, and no `unverifiedAgainstLive`.
- Judgment-routed categories are citation-grounded but stay `needs-review`, `sourceTier: llm`, and
  never verify automatically.

`tiers.artifact_tier(doc)` keeps LLM-sourced candidates advisory for §7.2/§7.5, while graduated
confirmation findings behave like Tier-A engine output.

## Go/no-go evidence — the recall eval

`tests/test_gap_finder.py` and `tests/test_copilot_gap_validation.py` against
`tests/fixtures/sample-gap-finder/`: payments has a **planted** missing-timeout gap, notifications
is an unguarded synchronous dependency, ledger has a logged-and-swallowed write failure, and the
report job is scheduled without job/runbook metadata. Shipping (`@TimeLimiter`) and refunds
(unlocatable anchor) remain negative controls in the truth/harness tests.

```
$ sre-kb gap-finder --target tests/fixtures/sample-gap-finder
gap-finder: 4 proposal(s) -> 4 kept (4 confirmed + 0 routed), 0 dropped
  [confirmed   ] swallowed-failure on ledgerRepository @ .../LedgerWriter.java:23-25
  [confirmed   ] undocumented-job on emitDailyReconciliation @ .../ReportJob.java:11-11
  [confirmed   ] missing-timeout on payments-api @ .../PaymentsClient.java:22-22
  [confirmed   ] unguarded-critical-dependency on notifications-api @ .../NotificationsClient.java:20-20
  needs-review: 2
  verified: 2
```

- **Recall** — all four planted expected gaps are surfaced.
- **Non-circular** — every proposal is grounded by verbatim bytes and then re-derived by the
  engine; the shipping/refunds controls still prove refutation and unlocatable-drop behavior.
- **Tier behavior** — refutation-probe absence gaps (`missing-timeout`,
  `unguarded-critical-dependency`) land `needs-review`, `source_tier=llm`; confirmation-probe gaps
  (`swallowed-failure`, `undocumented-job`) graduate to `source_tier=ast` and verify.

## Real-Copilot validation harness

HYBRID-PLAN §9.5 item 1 is closed for the sample target by the checked-in proposal/truth/report
triple from the real Copilot run:

- `tests/fixtures/sample-gap-finder/.sre/gap-proposals.json` was produced by a real Copilot run
  using `.github/skills/sre-gap-finder/SKILL.md`.
- `tests/fixtures/sample-gap-finder/.sre/gap-truth.json` records the four planted expected gaps and
  two negative controls.
- `tests/fixtures/sample-gap-finder/.sre/gap-validation-report.json` records
  expected/proposed/grounded/kept/confirmed all at 4, with proposal/kept recall and precision all
  `1.00`.

The engine still does not call a model; the manual boundary for a fresh run is explicit:

1. Run `sre-kb run --target <service> --to-stage scaffold` if you want a fresh context pack.
2. In VS Code, run Copilot with `.github/skills/sre-gap-finder/SKILL.md` and save the answer to
   `<service>/.sre/gap-proposals.json`.
3. Create a target-specific truth file, for example:

```json
{"expected": [{"category": "missing-timeout", "target": "payments-api"}],
 "controls": [{"category": "missing-timeout", "target": "shipping-api"}]}
```

4. Measure it:

```bash
sre-kb copilot-gap-validate \
  --target <service> \
  --truth <service>/.sre/gap-truth.json \
  --report .work/real-copilot-gap-validation.json
```

The report separates raw proposal quality from post-grounding quality: proposal recall/precision,
kept recall/precision, grounded rate, missed expected gaps, proposed controls, and false-positive
survivors. A real run should archive the saved Copilot proposals, the truth file, and the JSON
report together so the §9.5 claim is reproducible.

First real-Copilot sample result: the 2026-06-07 run against `sample-gap-finder` wrote
`tests/fixtures/sample-gap-finder/.sre/gap-proposals.json` and archived
`tests/fixtures/sample-gap-finder/.sre/gap-validation-report.json`.
It measured `expected=4 proposed=4 grounded=4 kept=4 confirmed=4`, proposal/kept recall and
precision all `1.00`, `groundedRate=1.00`, and zero false-positive survivors. Two findings graduated
to Tier-A/`verified` (`swallowed-failure`, `undocumented-job`); two remained Tier-B/`needs-review`
(`missing-timeout`, `unguarded-critical-dependency`). This closes HYBRID-PLAN §9.5 item 1 for the
sample target only; §9.5 item 2 remains open until multiple real services measure noise.

The refutation probe also generalizes to the bundled .NET sample (`InventoryClient.cs`: a genuine
Polly-breaker-but-no-timeout gap → confirmed) and refutes the Spring `InventoryClient` that carries
`@TimeLimiter`.

## Wiring

| Piece | Where |
|---|---|
| Prompt (LLM half) | `.github/skills/sre-gap-finder/SKILL.md` — wraps the vendored `assess-resiliency` skill (`@00b3071`) in the pointer-generator contract |
| Context pack | `synth/gap_prompt.build_gap_context` (nonce-fenced, content-preserving so anchors round-trip) |
| Collector (engine half) | `collectors/llm/gap_finder.py` — load → locate → stamp → re-derive |
| Re-derivation | `signatures.fires(concern, …)` per `_REFUTING_CONCERNS` (target-scoped in config) — the same library Tier-A uses |
| Artifact | `ResiliencyGap` (schema + registry row, phase P4); refutation/judgment gaps stay `needs-review`, `source_tier=llm`; confirmation gaps can graduate to `source_tier=ast` |
| Pipeline + gating | `pipeline/gap_finder.py` |
| CLI | `sre-kb gap-finder --target <repo> [--proposals <file>]` |

The engine still **never calls a model**: it ingests a `.sre/gap-proposals.json` Copilot already
wrote, exactly as `challenge-apply` ingests Copilot's verdicts.

## Grounded probes

Two probe *classes*, both firing the *shared* signatures / detectors so they can't drift from Tier-A.

**Refutation probes** (`_REFUTING_CONCERNS`) ground an *absence* — the gap survives only if the
refuting signature fires **nowhere** checked:

| Category | Refuted when (in scope) any of these signatures fire | Tier |
|---|---|---|
| `missing-timeout` | `timeout` | llm → `needs-review` |
| `unguarded-critical-dependency` | `circuit-breaker` · `fallback` · `timeout` | llm → `needs-review` |

Config probing is **target-scoped**: a config block only refutes a gap if it names the dependency's
resilience instance (the breaker/limiter `name=` on the call site, or the proposed target), so a
timeout for some *other* client in the same `application.yml` can't refute it.

**Confirmation probe** (`_CONFIRMING_CATEGORIES`, §9.4) — opposite polarity: the deterministic rule
firing **at the LLM's pointer** *confirms* the gap, and because the engine re-derived it, the finding
**graduates to Tier-A** (`source_tier=ast`) and reaches `verified` through the normal gate:

| Category | Confirmed when, at the pointer… | Tier |
|---|---|---|
| `swallowed-failure` | the AST swallow detector (`Call.swallow`) fires | **ast → can reach `verified`** |
| `undocumented-job` | the shared `scheduled` signature fires (`@Scheduled`, Quartz, Celery/APScheduler, `@repeat_every`) | **ast → can reach `verified`** |

The recall this adds: the relevant detector already exists, but the collectors don't emit a fact for
it at the proposed site — swallows are emitted only for Kafka egress, and there is no `ScheduledJob`
collector at all — so the gap-finder surfaces engine-detectable findings at the call sites the
collectors ignore (a DB write, an HTTP call, a cron job with no Flow/runbook). A pointer where the
rule doesn't fire is dropped — the LLM can't assert what the engine can't reproduce. This is the
smallest concrete instance of the §7.9 **graduation loop**, and it consciously widens the trust
boundary (an LLM-chosen location can now produce a hard Tier-A guardrail — sound because the engine's
deterministic rule fired on hashed bytes; see HYBRID-PLAN §9.5 ④).

**Judgment routing** (`_JUDGMENT_CATEGORIES`, §7.9) — the third path, for categories no
deterministic probe can ground (`data-loss-path`, `missing-idempotency`, `unbounded-resource`):
"is this a data-loss path / a non-idempotent retry?" is a reasoning call. The engine still grounds
the *citation* (the anchor must locate verbatim) and surfaces them as `routed` Tier-B candidates —
`source_tier=llm`, `rederivation: judgment`, **needs-review, never verified**, subject to the noise
budget — for the human/Copilot oracle. A located judgment gap is `kept` but not `confirmed`; an
unlocatable one is still dropped.

A **noise budget** (`gap_finder.max_candidates`, default 25) ranks the *llm-tier* survivors
(refutation survivors + routed judgment gaps) by severity and caps the rest as `capped`; graduated
Tier-A findings are engine-confirmed, not candidates, so they are never capped.

**Cross-stack.** The probes are language-neutral: `_locate`/`_enclosing_type` handle Java, C#, and
Python, and the swallow detector now reads Python `try/except` (`code_model._py_enclosing_swallow`),
so `swallowed-failure` confirms-and-graduates on a FastAPI handler just as it does on Java. (Python
`missing-timeout` needs httpx client-call detection wired in — a follow-up.)

## Honest limitations (why it's still a spike)

- ~~**The LLM half has never run for real.**~~ Closed for the sample target: a real Copilot run
  produced `tests/fixtures/sample-gap-finder/.sre/gap-proposals.json`, and
  `tests/fixtures/sample-gap-finder/.sre/gap-validation-report.json` measures four proposed,
  grounded, kept, and confirmed gaps with 1.00 proposal/kept recall and precision. Precision at
  larger scale is still unmeasured (HYBRID-PLAN §9.5 item 2).
- **All seven §7.9 categories now have a home:** four are deterministically grounded
  (`missing-timeout`, `unguarded-critical-dependency`, `swallowed-failure`, `undocumented-job`);
  three are judgment-routed (`data-loss-path`, `missing-idempotency`, `unbounded-resource`) —
  located but not re-derived, surfaced as `needs-review` for the oracle. The judgment ones are pure
  LLM assertions modulo the citation, so they lean entirely on the noise budget + human review.
- **Signatures are text-broad.** Re-derivation reuses the shared signature regexes, some of which
  match plain words (e.g. `fallback`), so a code *comment* mentioning a pattern can refute a real
  gap. Acceptable here (worst case: a false negative a human never sees) but a reason the probes
  aren't airtight.
- **In-scope/per-file re-derivation**, the same documented boundary as the AST model: a "confirmed"
  gap is *plausible*, not *proven* — hence `needs-review`, never `verified`.
- ~~**Standalone path.**~~ Resolved: `sre-kb run` now auto-detects `.sre/gap-proposals.json` and
  routes survivors through the shared validate/gate path (HYBRID-PLAN §9.3 item 1). The standalone
  `sre-kb gap-finder` CLI remains for proposals-only runs.
- **Graduation is demonstrated, not generalized.** `swallowed-failure` and `undocumented-job`
  already show confirmation-probe graduation at a pointer. The next strategic step is the reusable
  loop: when a recurring human-confirmed category proves stable, promote it into a deterministic
  Tier-A signature/collector so it drops out of the LLM frontier.
