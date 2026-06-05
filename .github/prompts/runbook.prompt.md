---
mode: agent
description: "Write grounded runbooks for the generated alerts."
---

For each `Alert`, write a `Runbook`:

1. Symptoms = the real log line + observable effect; diagnosis steps each point to the
   code/config/endpoint to inspect (with an evidence ref).
2. Remediation stays within PCF instance limits; only suggest retry/replay where the
   step is `idempotent`/`retrySafe`. Keep the "GENERATED — verify before executing" banner.
3. Validate; leave `needs-review` if any step can't be grounded.
