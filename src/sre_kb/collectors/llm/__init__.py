"""Tier-B (LLM) collectors — SPIKE.

Unlike the deterministic AST/config collectors under their sibling packages, a Tier-B
collector does not *read* facts from the source. It ingests *proposals* an LLM (Copilot,
running a vendored skill) produced from the engine's facts + the code, then the ENGINE —
never the LLM — locates each proposal in the bytes, stamps it `path:line:excerptHash`,
and independently re-derives it with the same kind of deterministic rule Tier A uses.

The contract is the non-circular Tier-B contract from `docs/HYBRID-PLAN.md` §4:

  1. The LLM is a *pointer/hypothesis generator*, not a fact source. It proposes a claim
     plus the excerpt *text* it is pointing at — never a line number (LLMs are unreliable
     at exact lines).
  2. The engine *locates* those bytes itself and stamps the citation, so a hallucinated
     line or a fabricated quote simply fails to ground and is dropped.
  3. The engine *re-derives* the claim deterministically at that location. The LLM only
     widened coverage; the assertion is the engine's.

Nothing a Tier-B collector emits can auto-verify: every fact rides `source_tier="llm"`
and lands as `needs-review`.
"""
