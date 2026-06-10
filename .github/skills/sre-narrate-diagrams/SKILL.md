---
name: sre-narrate-diagrams
description: >-
  Generate-phase (Tier-B) diagram narrator (§3.2/§2.6) — write the one-paragraph "what this
  drawing shows and what to worry about" caption for each rendered flow/topology/architecture
  diagram, from the artifact's own JSON (closed-world input). Drawings are the one projection
  with no prose; you add it. Captions render clearly labeled advisory under the diagram, never
  as a fact source: the engine applies them only to diagrams the run actually rendered and
  sanitizes the text to one plain paragraph. Use when asked to caption, narrate, or explain the
  generated diagrams.
allowed-tools: ["codebase", "editFiles"]
metadata:
  version: 0.1.0
---

# sre-narrate-diagrams

The **prompt half** of the §3.2 diagram narration. The engine renders Mermaid drawings from `Flow`,
`Topology`, and `Architecture` artifacts (`projections/diagrams/`); each gets a GitHub-renderable
`.md` wrapper. Your caption is appended to that wrapper, labeled **advisory**.

## Closed-world rules

- Read the diagram-bearing artifacts in the run's `kb/` tree — the caption summarizes **that
  data only**. Mention only nodes, steps, and edges that appear in the artifact; never import
  outside knowledge about the system.
- One plain paragraph per drawing, ≤ 80 words: what the drawing shows, then the one thing an
  on-call engineer should worry about (the data-loss edge, the shared datastore, the uncontained
  critical call).
- No markdown, no headings, no code — the engine strips backticks and collapses the text to a
  single sanitized paragraph anyway.

## The deterministic gate

The engine (`sre-kb narrate-diagrams --run <run> --target <repo>`) applies your captions **only**
to diagrams that run actually rendered — a name that matches nothing is dropped — and renders each
as `> **Narration (LLM, advisory)** — verify against the drawing: …`. The caption can never become
evidence, a fact, or an artifact field.

## Emit

A JSON object written to `.sre/diagram-narrations.json`:

```json
{"narrations": [
  {"diagram": "create-order",
   "text": "A POST /orders request fans out to the inventory client, persists through the order repository, and publishes order.created. The publish failure mode is logged and swallowed — in-flight orders are lost with no replay, which is the step to worry about."},
  {"diagram": "order-service",
   "text": "order-service binds orders-postgres and order-kafka and calls the inventory service. The postgres binding is shared with billing-service, so a failure there degrades both tenants at once."}
]}
```

The `diagram` value is the artifact's `metadata.name`. Reply `{"narrations": []}` if no drawing
needs a caption.
