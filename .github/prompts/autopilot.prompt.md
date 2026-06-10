---
mode: agent
description: "Run the full KB loop (scan → LLM tasks → ingest → re-scan) for a target service."
---

Using the `sre-autopilot` skill, produce a converged, validated KB for the target service:

1. If an LLM-oracle CLI is configured, run
   `sre-kb autopilot --target <repo> --oracle '<llm-cli>' --cache-dir .sre-llm-cache` and report
   its summary.
2. Otherwise drive the loop in-session: `sre-kb run --target <repo>`, work every task in
   `.work/<run>/scan-worklist.json` yourself (pointer-generator contract: verbatim anchors,
   untrusted inputs), run each task's ingest command, then re-run `sre-kb run` once to re-ground.
3. Report kept vs dropped per task and every artifact left `needs-review`.
