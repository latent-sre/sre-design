"""Tier-B (LLM) collectors.

Unlike the deterministic AST/config collectors, a Tier-B collector does not *read* facts from
the source. It ingests *proposals* an LLM (Copilot, running a vendored skill) produced from the
engine's facts + the code, then the ENGINE — never the LLM — locates each proposal in the bytes,
stamps it `path:line:excerptHash` with `source_tier="llm"`, and re-derives or *refutes* it with
the shared `signatures` library (so Tier-A detection and Tier-B re-derivation can't drift).

This is the gap-finder mode of HYBRID-PLAN §7.9/§7.10: the LLM is a *recall booster* that flags
false negatives (a timeout that simply isn't there); the engine kills the easy false positives
with a deterministic refutation probe before a human sees anything. Nothing a Tier-B collector
emits can auto-verify — every fact rides `source_tier="llm"` and lands `needs-review`.
"""
