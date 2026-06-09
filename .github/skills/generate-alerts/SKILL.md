---
name: generate-alerts
description: >-
  Generate-phase (Tier-B) alert drafter (coverage #19) — propose which parsed error/warn log lines
  warrant an alert, the alert-fatigue judgment the engine can't make. The engine already parses every
  log statement and auto-alerts the one it can prove (a swallowed-publish failure); you widen that to
  the other alert-worthy log lines. Point at a verbatim log line; the engine grounds it against its own
  parsed log-statement facts, refutes any info/debug line by level, derives the search query itself,
  and drafts a needs-review log-pattern Alert. Use when asked to draft alerts, suggest what to page on,
  or turn error logs into alerts. Nothing you propose auto-verifies.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# generate-alerts

The **prompt half** of the coverage #19 alert drafter. The engine's `java_spring.log_statements`
collector parses every log call (its level, whether the message is parameterized) and the scaffolder
already emits a log-pattern Alert for a **swallowed publish channel** — the one error log it can prove
is alert-worthy. You add the **judgment** it can't byte-prove: *which other* error/warn log lines are
worth paging on, and which are routine noise (alert fatigue).

## Scope — point at log lines, judge alert-worthiness only

The engine hands you the context pack plus the log statements it parsed. Your job is a single judgment
per candidate: **does this log line warrant an alert?** Good candidates are error/warn lines that are
the *only* signal of a real failure (a swallowed exception, a dropped message, a failed external call
with no metric). Skip:

- **info/debug/trace lines** — the engine refutes these by level; do not propose them.
- **routine validation/business misses logged at error** — high-volume, low-signal; that is the
  alert-fatigue trap, not an alert.
- **lines a metric/burn-rate alert already covers** — the engine drafts those deterministically.

## The non-circular contract (same as sre-gap-finder)

You **point**, the engine **judges**:

1. For each candidate, emit a proposal whose `anchor` is a **verbatim excerpt** of the log line —
   copied exactly from one UNTRUSTED block. Never a line number.
2. The **engine** locates those bytes, confirms a parsed `observability.log.statement` sits there, and
   **refutes** anything that isn't `error`/`warn` (you don't page on a debug log). It then derives the
   search query from the byte-grounded message literal itself — the query is the engine's, not yours.
3. Survivors are Tier-B `needs-review` `Alert` artifacts (`source_tier: llm`), rendered through the
   deterministic per-backend adapters. You widened *which* logs alert; the engine made every
   deterministic call.

## Emit

A JSON object written to `.sre/alert-proposals.json`:

```json
{"proposals": [
  {"anchor": "log.error(\"publish failed for order \" + id, e);", "severity": "high",
   "rationale": "the only signal that an order event was dropped — no metric exists; page until one does"},
  {"anchor": "log.warn(\"gateway timeout, retrying account={}\", account, e);", "severity": "medium",
   "rationale": "a sustained rate of these warns is the leading indicator of a gateway outage"}
]}
```

`severity` is optional (defaults from the log level: error -> high, warn -> medium). Every surviving
proposal is Tier-B `needs-review`. The engine runs `sre-kb generate-alerts` to re-ground them.
