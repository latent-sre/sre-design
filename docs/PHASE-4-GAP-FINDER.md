# Phase 4 — LLM gap-finder (SPIKE)

The first **Tier-B (LLM) collector**: an LLM proposes resiliency gaps the deterministic AST
collectors missed (e.g. a client call with no timeout), and the **engine** — never the LLM —
locates each proposal, stamps it `path:line:excerptHash`, re-derives it, and lands it as
`needs-review`. This is a *spike*, not a full build: one collector, one re-derivation rule
(timeout), one recall test. It exists to answer one question — **is an LLM gap-finder, fenced
behind the engine's byte-grounding, signal or noise?**

## The non-circular contract (why this isn't "LLM grades itself")

Naïvely, "the LLM emits `path:line` and the engine recomputes the hash" is circular — the hash
only proves the LLM quoted bytes that exist, and a substring grounding check only proves it
quoted its own keyword (`validation/challenge.py:9-13`). So instead, per `HYBRID-PLAN.md` §4:

1. **The LLM is a pointer-generator, not a fact source.** It quotes the *verbatim excerpt* a gap
   lives at — never a line number (LLMs are unreliable at exact lines; the engine is not).
2. **The engine locates the bytes itself** and stamps `path:line:excerptHash`
   (`collectors/llm/gap_finder.py:_locate` + `ctx.evidence`). A quote it can't find verbatim is
   dropped → no fabricated citations.
3. **The engine re-derives the gap deterministically** with the same kind of rule Tier A uses
   (`_rederive_timeout`: there IS an outbound client call AND no timeout configured in scope). A
   proposal it can refute is dropped → the LLM cannot assert a gap that isn't there.

The LLM only **widens coverage**; the **engine makes the assertion**. And because a missing
timeout being a *problem here* is ultimately a judgment call, every surfaced gap lands
`needs-review` with `confidence` below the verified floor — **nothing LLM-proposed can
auto-verify.**

## Wiring

| Piece | Where |
|---|---|
| Prompt (the LLM half) | `.github/skills/sre-gap-finder/SKILL.md` — wraps the vendored `assess-resiliency` skill (`references/assess-resiliency.SKILL.md`, from `latent-sre/resiliency-skills@00b3071`) in the pointer-generator output contract |
| Context pack the engine hands Copilot | `synth/gap_prompt.build_gap_context` (known facts + untrusted call sites + JSON answer contract) |
| Collector (the engine half) | `collectors/llm/gap_finder.py` — load → locate → stamp → re-derive |
| Trust tier | `Fact.source_tier = "llm"` (HYBRID-PLAN Phase 0 seam) |
| Artifact | `ResiliencyGap` (schema + registry row, phase `P4`); `provenanceMode: llm-asserted`, `status: needs-review` |
| Pipeline + gating | `pipeline/gap_finder.py` (scaffold → structural → provenance → final-status gate) |
| CLI | `sre-kb gap-finder --target <repo> [--proposals <file>]` |

The engine still **never calls a model**: it ingests a `.sre/gap-proposals.json` Copilot already
wrote, exactly as `challenge-apply` ingests Copilot's verdicts.

## Go/no-go evidence — the recall test

`tests/test_gap_finder.py` against `tests/fixtures/sample-gap-finder/` (a payments client with a
**planted** missing-timeout gap, a shipping client that *has* `@TimeLimiter` as a control, and a
simulated Copilot output carrying three proposals):

```
$ sre-kb gap-finder --target tests/fixtures/sample-gap-finder
gap-finder: 3 proposal(s) -> 1 confirmed gap(s), 2 dropped
  [confirmed   ] timeout on payments-api  @ .../PaymentsClient.java:22-22  — outbound client call with no timeout
  [refuted     ] timeout on shipping-api  @ .../ShippingClient.java:24-24  — a timeout IS configured in scope
  [unlocatable ] timeout on refunds-api                                    — anchor not found verbatim in the source
  needs-review: 1
```

- **Recall** — the planted gap is surfaced.
- **Non-circular** — the false gap (timeout actually present) is *refuted*, and the hallucinated
  gap (quote doesn't exist) is *dropped*. The LLM can neither assert a phantom gap nor fabricate
  a citation.
- **Grounded** — the surfaced gap carries a real, hash-checkable `path:line:excerptHash`.
- **No auto-verify** — it lands `needs-review`, schema-valid, `confidence 0.5 < 0.7`.

The re-derivation also generalizes to the bundled .NET sample (`InventoryClient.cs`: a genuine
Polly-breaker-but-no-timeout gap → *confirmed*) and refutes the Spring `InventoryClient` that
carries `@TimeLimiter`.

## Verdict: signal, not noise — continue

The spike works **because the engine, not the LLM, is the gate.** LLM noise is contained by
construction: every false positive and hallucination in this run was dropped by deterministic
re-derivation, so nothing un-grounded reaches a human. That is the property the hybrid is built
on, and it held.

Honest limitations (why it's a spike and lands `needs-review`, not a shipped feature):

- **One rule only.** Only `timeout` has a re-derivation rule; other patterns are recorded but not
  asserted. Each new pattern needs its own deterministic confirmation, or it stays a judgment
  call routed to the (not-yet-live) `LLMChallenger`.
- **The re-derivation is in-scope/per-file**, same documented boundary as the AST model: a timeout
  configured elsewhere (a `RestTemplate` bean, a gateway, a sidecar) would not be seen, so a
  "confirmed" gap is *plausible*, not *proven* — hence `needs-review`, never `verified`.
- **Recall depends on the LLM** pointing at the right call site; this spike measures precision of
  the *grounding gate*, not the LLM's own recall (that needs a labelled corpus).

Next, per the hybrid plan: more re-derivation rules (retry-without-budget, missing bulkhead), and
wire the judgment-call residue to a live `LLMChallenger` oracle instead of defaulting to review.
