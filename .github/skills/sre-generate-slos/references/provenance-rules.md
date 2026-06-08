# Provenance rules (non-negotiable)

The SRE knowledge base is **validated**. Every claim must be traceable to code.

- **Cite only what's in context.** Reference only `path:line` ranges that appear in the
  provided excerpts. Never invent files, line numbers, metric names, or log strings.
- **Don't touch `excerptHash`.** It is a SHA-256 of the exact cited bytes, recomputed by
  the validator. If your citation doesn't match the bytes, the artifact is auto-downgraded
  to `needs-review`.
- **Unknown ⇒ `needs-review`.** If you can't ground a claim, lower `confidence` and set
  `status: needs-review`. Do not fabricate to reach `verified`.
- **No invented thresholds or queries.** Alert `expr` may reference only metrics/log
  patterns that actually exist in the facts.
