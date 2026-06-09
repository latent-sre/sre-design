# SRE KB schemas

This directory is the **contract** for every artifact the engine emits. It is intentionally small and
declarative so the codebase is easy to scan: to understand what an artifact may contain, read the
schema; to understand how a kind is wired, read `registry.yaml`; to understand which enum values are
legal, read `taxonomy.yaml`.

## Files

| File | Role |
|---|---|
| `_envelope.schema.json` | The **shared envelope** every artifact embeds: `apiVersion`, `kind`, `metadata`, `spec`, `status`, plus optional `evidence` / `confidence` / `provenanceMode` / `crossRefs` / `generatedBy` / `unverifiedAgainstLive`. Provenance, confidence, and status are first-class — this is what makes the KB *validated* rather than just structured. |
| `v1alpha1/<Kind>.schema.json` | One per kind. Constrains **only** `kind` (a `const`) and the kind-specific `spec`. The envelope owns everything else. |
| `registry.yaml` | The one declarative table mapping each kind → `schema` / `collectors` / `prompt` / `phase` / `renderer`. Adding a kind is one row here (see below). |
| `taxonomy.yaml` | The single source of truth for the controlled vocabularies (`severity`, `status`, `ownership`, …) and severity-alias reconciliation, so enums can't drift across schemas and code. |

## The two-pass validation contract (read this before editing a schema)

An artifact is validated in **two passes** (`validation/structural.py`):

1. **Envelope pass** — every artifact is validated against `_envelope.schema.json`. The envelope sets
   `additionalProperties: false` at its **root**, so it is the gate that rejects unknown *top-level*
   keys (a stray `apiVerison` typo, an injected field, etc.).
2. **Per-kind pass** — if `v1alpha1/<Kind>.schema.json` exists, the artifact is *also* validated
   against it. The per-kind schema enumerates the `spec` fields and sets `additionalProperties: false`
   **on `spec`**, so it is the gate that rejects unknown *spec* keys.

> ### ⚠️ Per-kind schemas must NOT set `additionalProperties: false` at their root
>
> A per-kind schema only lists `kind` and `spec`. The full artifact also carries `apiVersion`,
> `metadata`, `status`, `evidence`, etc. — which the envelope, not the per-kind schema, knows about.
> Adding root-level `additionalProperties: false` to a per-kind schema would make the per-kind pass
> reject **every valid artifact**, because `apiVersion`/`metadata`/`status`/… would all count as
> "additional." Root strictness lives on the envelope **on purpose**; keep per-kind strictness scoped
> to `spec`.

This split is deliberate. Compared to inlining the governance block into every schema (the approach in
the sibling `resiliency-skills` engine), the shared envelope is DRY and gives one place to evolve
provenance/confidence/status — every kind inherits the change automatically.

## Adding a kind

1. Add `v1alpha1/<Kind>.schema.json` — `kind` as a `const`, a `spec` object with
   `additionalProperties: false`, draft 2020-12, an `$id`, and a `title`.
2. Add a row to `registry.yaml` under `kinds:` (schema path + `phase`; `collectors` / `prompt` /
   `renderer` as applicable).
3. If the kind has a projection, declare its `renderer` and implement it in
   `render/project.py::_PROJECTION_RENDERERS`.
4. Reuse enums from `taxonomy.yaml` rather than hard-coding a new vocabulary.

`tests/test_registry_governance.py` and `tests/test_schema_governance.py` keep these in lock-step: a
kind can't ship without a schema file, a schema file can't be orphaned from the registry, a declared
renderer must be implemented (and vice versa), and the `spec` allow-list / `ownership` enum are
enforced. Run `make test` before declaring a schema change done.
