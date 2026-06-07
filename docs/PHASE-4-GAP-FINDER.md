# Phase 4 — LLM gap-finder (spike)

The first **Tier-B (LLM) collector**, built as a spike on the primitives already in `main`
(`signatures.py`, `tiers.py`, `Evidence.source_tier`). It implements the recall mode of
HYBRID-PLAN **§7.9/§7.10**: Copilot proposes resiliency gaps the AST missed (e.g. a critical client
call with no timeout); the **engine** — never the LLM — locates each proposal, stamps it
`path:line:excerptHash`, and re-derives or *refutes* it deterministically. Nothing it proposes can
auto-verify.

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
golden-corpus example), forced to:

- `status: needs-review` (never verified), `confidence: 0.5` (below the verified floor),
- `provenanceMode: llm-asserted`, `unverifiedAgainstLive: true` (an *absence* isn't checkable
  offline), `spec.sourceTier: llm`, and the `checked:` honest-negative trail.

`tiers.artifact_tier(doc)` rolls this up to `llm`, so §7.2 guardrails keep it advisory and §7.5
labels it "LLM-proposed".

## Go/no-go evidence — the recall eval

`tests/test_gap_finder.py` against `tests/fixtures/sample-gap-finder/`: a payments client with a
**planted** missing-timeout gap, a shipping client that *has* `@TimeLimiter` (control), and a
simulated Copilot output carrying three proposals.

```
$ sre-kb gap-finder --target tests/fixtures/sample-gap-finder
gap-finder: 3 proposal(s) -> 1 confirmed gap(s), 2 dropped
  [confirmed   ] missing-timeout on payments-api  @ .../PaymentsClient.java:22-22  — no timeout signature fires in 2 checked location(s)
  [refuted     ] missing-timeout on shipping-api  @ .../ShippingClient.java:24-24  — the timeout signature fires in scope
  [unlocatable ] missing-timeout on refunds-api                                    — anchor not found verbatim in the source
  needs-review: 1
```

- **Recall** — the planted gap is surfaced.
- **Non-circular** — the false gap (timeout actually present) is *refuted* by the shared signature;
  the hallucinated gap (quote doesn't exist) is *dropped*.
- **Grounded** — the surfaced gap carries a real, hash-checkable `path:line:excerptHash`,
  `source_tier=llm`.
- **No auto-verify** — it lands `needs-review`, schema-valid, `confidence 0.5 < 0.7`.

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
| Artifact | `ResiliencyGap` (schema + registry row, phase P4); `needs-review`, `source_tier=llm` |
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

The recall this adds: the swallow detector already runs on *every* call, but the collectors emit
`swallowed.failure` **facts** only for Kafka egress — so the gap-finder surfaces engine-detectable
swallows at the call sites the collectors ignore (a DB write, an HTTP call). A pointer where the rule
doesn't fire is dropped — the LLM can't assert a swallow the engine can't reproduce. This is the
smallest concrete instance of the §7.9 **graduation loop**, and it consciously widens the trust
boundary (an LLM-chosen location can now produce a hard Tier-A guardrail — sound because the engine's
deterministic rule fired on hashed bytes; see HYBRID-PLAN §9.5 ④).

A **noise budget** (`gap_finder.max_candidates`, default 25) ranks the *llm-tier* survivors by
severity and caps the rest as `capped`; graduated Tier-A findings are engine-confirmed, not
candidates, so they are never capped.

## Honest limitations (why it's still a spike)

- **The LLM half has never run for real** — every test uses a hand-written proposals file, so recall
  and precision on real code are *unmeasured* (HYBRID-PLAN §9.5 ①/②).
- **Three categories grounded** (`missing-timeout`, `unguarded-critical-dependency`,
  `swallowed-failure`). The rest (`data-loss-path`, `missing-idempotency`, `undocumented-job`,
  `unbounded-resource`) are recorded but not asserted (no probe ⇒ can't ground).
- **Signatures are text-broad.** Re-derivation reuses the shared signature regexes, some of which
  match plain words (e.g. `fallback`), so a code *comment* mentioning a pattern can refute a real
  gap. Acceptable here (worst case: a false negative a human never sees) but a reason the probes
  aren't airtight.
- **In-scope/per-file re-derivation**, the same documented boundary as the AST model: a "confirmed"
  gap is *plausible*, not *proven* — hence `needs-review`, never `verified`.
- ~~**Standalone path.**~~ Resolved: `sre-kb run` now auto-detects `.sre/gap-proposals.json` and
  routes survivors through the shared validate/gate path (HYBRID-PLAN §9.3 item 1). The standalone
  `sre-kb gap-finder` CLI remains for proposals-only runs.
- **No graduation loop yet** (§7.9): promoting a recurring, human-confirmed gap category to a
  deterministic Tier-A signature (so it drops out of the LLM's frontier) is the next strategic step.
- **`swallowed-failure` is the natural next probe** — and the cleanest instance of graduation: re-run
  the deterministic swallow rule at the pointer and, *if it fires*, promote the finding to Tier-A.
