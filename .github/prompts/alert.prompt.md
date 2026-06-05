---
mode: agent
description: "Derive grounded alerts from flows, logging format, and resiliency facts."
---

Derive `Alert` artifacts for the scanned service:

1. For each swallowed-failure / uncontained failure mode in the validated `Flow`s,
   propose an alert whose `expr` references only **real** log patterns (match the
   `Observability` logging format) or **existing** metrics.
2. If the flow has an `SloSli`, use a multi-window error-budget burn-rate alert;
   otherwise emit a threshold alert with `status: needs-review` so a human sets the SLO.
3. Cite the same evidence as the underlying flow step, then validate.
