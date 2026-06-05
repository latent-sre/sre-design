---
mode: agent
description: "Build/repair the validated Flow artifacts for a scanned service."
---

Using the `sre-flow-analysis` skill, enrich the scaffolded `Flow` candidates in
`.work/<run>/candidates/` for the target service:

1. For each Flow, confirm the ordered steps and their failure modes against the cited
   code (do not add steps you can't cite).
2. Keep any `logged-and-swallowed` / `dataLossRisk` markers — they seed the Alert.
3. Run `sre-kb run --target <repo> --run <run> --to-stage validate` and fix flagged
   items until the Flow is `verified` (or correctly `needs-review`).
