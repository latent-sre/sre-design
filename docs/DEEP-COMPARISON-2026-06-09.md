# Deep comparison (round 2): rendering, templating, and schema/YAML formatting

Date: 2026-06-09

> **Scope.** This is a focused follow-up to an earlier `resiliency-skills` comparison (which covered
> publish hardening, secret gates, the skill taxonomy, and role separation; since retired — see git
> history). That review deliberately did **not** cover the *rendering / templating layer* or
> *schema/YAML/JSON formatting* — the dimensions this round
> targets, motivated by the goal of making the codebase "elite to scan and understand." The earlier
> publish-hardening / skill-taxonomy backlog (tracked in HYBRID-PLAN) is unchanged and not
> re-litigated here.

## Evidence boundary

Two double-pass scans were run over both repos (a broad fan-out read, then a second confirming pass on
the specific findings):

- `latent-sre/sre-design` `origin/main`: `87170630a3aff73e79fb8de84846ffdd79167561`
- `latent-sre/resiliency-skills` `origin/main`: `04e220e87d2e7d55296c3787bb11a645bfe0926e`

Validation of this change:

- `make test` (pytest) → **477 passed** (was 471 before this change; +6 new templating tests).
- `make lint` (ruff) → clean.
- The four migrated free-text renderers produce **byte-identical** output to the prior implementation,
  proven by a baseline diff over the golden fixtures (`copilot-instructions`, `runbook` with/without a
  flow, `mermaid` sequence/topology, plus empty/minimal edge cases). Behavior is unchanged; only the
  *form* of the rendering code changed.

## Headline finding (confirmed on both passes)

`sre-design` declares `jinja2>=3.1` as a runtime dependency (`pyproject.toml`) **but imported it
nowhere** — every textual output was produced by hand-built Python f-strings and `"\n".join(lines)`
across ~624 non-comment lines in `src/sre_kb/render/`. `resiliency-skills`, by contrast, has a small,
clean templating spine:

- `engine/src/latent_sre/templating.py` — a **sandboxed** Jinja2 environment factory + sanitizing
  filters + a fail-loud sentinel.
- `engine/templates/**/*.j2` — one template per alert-backend adapter, plus `runbook.md.j2` and the
  generated-repo scaffold files.
- `engine/src/latent_sre/render.py` — thin orchestration: load intent → build a context dict →
  `template.render(**ctx)`.

The dormant dependency was the single clearest "use the other repo's strength" opportunity.

### The key architectural nuance

`resiliency-skills` does **not** templatize everything, and that distinction is the right one to copy:

| Output shape | `resiliency-skills` | Correct technique | Why |
|---|---|---|---|
| Free-text **prose** (runbook md) | `runbook.md.j2` | Jinja template | large static text + small structure → a template is far more scannable than `join(lines)` |
| Line-oriented configs (Splunk `.conf`, Wavefront) | `*.j2` adapters | Jinja template + escaping filters | per-backend dialects vary; templates isolate each |
| **Mermaid diagrams** | `mermaid.py` (Python) | Python serializer | a graph walk with loops/participant-mapping reads better as code; sanitize via a shared filter |
| Structured **YAML/JSON** (alert `expr`, dashboard panels, catalog-info) | native dicts → serializer | Python dict + dumper | hand-templating a structured format invites quoting/injection bugs a real serializer cannot make |

The takeaway: **templatize prose, keep structured/graph serialization in Python, and centralize the
escaping in one place** that both sides share.

## What this change implements

This change adopts the pattern at the altitude the comparison repo actually uses it — no more, no less.

1. **New `src/sre_kb/render/templating.py`** — the keystone, mirroring `resiliency-skills/templating.py`:
   - A process-wide, cached `SandboxedEnvironment` (`autoescape=False` — outputs are Markdown, not
     HTML; `StrictUndefined` — a missing context key fails loud instead of shipping a silent blank;
     `trim_blocks`/`lstrip_blocks`/`keep_trailing_newline` for predictable whitespace).
   - The two repo-derived-value sanitizers as the **single definition**, registered as Jinja filters:
     `inline` (Markdown: collapse whitespace, drop backticks — kills newline-injected bullets and
     code-span breakout) and `mermaid` (diagram: collapse whitespace, strip diagram metacharacters).
   - An `HB` global for the semantic Markdown hard-break (two trailing spaces) so editors/formatters
     can't silently strip it.

2. **Two prose templates** under `src/sre_kb/render/templates/`:
   `copilot-instructions.md.j2` and `runbook.md.j2`. `render/copilot.py` now derives its rule/advisory/
   flow data in Python (unchanged logic) and renders the document through the template.

3. **Centralized escaping.** `render/diagrams.py` and `render/copilot.py` previously defined their own
   `_mm` / `_inline` sanitizers. Both now import the canonical implementations from `render.templating`,
   so the injection defenses have exactly one definition across templates and Python (this directly
   answers the first scan's top concern: "escaping is distributed"). The named injection-regression
   tests still pin both attacks.

4. **Packaging.** `render/templates/*.j2` ship as package data, so a wheel-installed engine resolves
   them at runtime (parity with how schemas/config already ship).

5. **Tests.** `tests/test_templating.py` pins the security guarantees (sandbox blocks attribute attacks,
   `StrictUndefined` fails loud, filters sanitize) so the new boundary can't silently regress.

### Deliberately *not* changed (with rationale)

A faithful "make it elite" pass also means **rejecting** lower-altitude or actively-wrong suggestions
the scans surfaced:

- **Do not templatize the Mermaid renderer.** It is a graph serializer; `resiliency-skills` keeps the
  equivalent (`mermaid.py`) in Python for the same reason. It now uses the shared `mermaid` filter.
- **Do not hand-template YAML/JSON outputs** (alert `expr`, dashboard panels, `catalog-info.yaml`).
  Building a dict and serializing is safer and already deterministic; templating them would *introduce*
  the quoting/injection class of bug. Left as-is by design.
- **Do not add `additionalProperties: false` to the root of the per-kind schemas.** A scan pass
  recommended this, but it is **wrong for sre-design's two-pass validation**: the shared
  `_envelope.schema.json` already enforces root strictness (it lists `apiVersion`/`metadata`/`status`/
  `evidence`/… and sets `additionalProperties: false`), while each per-kind schema validates only
  `kind` + `spec`. Adding root strictness to a per-kind schema would reject every valid artifact,
  because `apiVersion`, `metadata`, `status`, etc. would all count as "additional." sre-design's
  centralized-envelope design is *stronger* than `resiliency-skills`' inlined-governance-per-schema
  approach (one place to evolve governance; DRY), and should be kept.
- **Do not switch YAML emission to `ruamel.yaml` + `sort_keys=True`.** `resiliency-skills` sorts keys
  for content-addressable hashing; sre-design intentionally uses `sort_keys=False` to preserve authorial
  order for human-readable artifacts, and already canonicalizes via JSON `sort_keys=True` *only* where
  it needs a content signature (`drift/diff.py`). A blanket switch would hurt readability and add a
  dependency for no current consumer. (If/when manifest-hash clobber-protection lands — the
  manifest-backed no-clobber publish work in HYBRID-PLAN — revisit a dedicated canonical-dump helper,
  scoped to that path.)

## Schema/YAML comparison summary

Both repos use JSON Schema **draft 2020-12**, `$id` URIs, 2-space indentation, and `additionalProperties:
false` on nested objects. The substantive differences:

| Dimension | `sre-design` | `resiliency-skills` | Verdict |
|---|---|---|---|
| Governance reuse | Centralized `_envelope.schema.json`, `$ref`'d `$defs`, applied via a 2-pass validator | Governance block inlined + `$defs` duplicated in every schema | **Keep sre-design's** (DRY, one evolution point) |
| Per-kind schema scope | Only `kind` + `spec` | Whole-artifact shape | sre-design's is lighter; keep |
| Registry | `schemas/registry.yaml` (kind → schema/collectors/prompt/phase/renderer) | `registry.py` dataclass (kind → schema/dest/renderer) | sre-design's is **richer**; lock-step both ways after this change |
| Evidence model | Byte-grounded `evidence[]` (path/line/`excerptHash`/detector/tier) | provenance block only | **sre-design's is materially stronger** |
| Golden examples | Full envelope + evidence per kind (`tests/fixtures/golden/`) | `examples/golden/` per kind | both good |

### Schema/registry follow-ups — resolved after architecture inspection

Three follow-ups were flagged from the scan. Implementing them required first checking that each
*maps to sre-design's actual architecture* rather than transplanting a `resiliency-skills` shape. Two
did not map; one did, and it pulled in a real adjacent fix.

- **R-S3 — `schemas/README.md` (DONE).** Added a short README documenting the four schema files, the
  two-pass validation contract, and an explicit ⚠️ on why per-kind schemas must **not** set root
  `additionalProperties: false` (root strictness lives on the shared envelope by design). This makes
  the (correct) design discoverable so a future contributor doesn't "helpfully" add it per-kind. The
  sibling repo documents its governance block in `engine/schemas/_provenance.md`; this is the analogue.
- **R-S1b — Orphan-schema governance test (DONE, adjacent to R-S1).** The original framing ("split
  control-plane kinds") does **not** apply: sre-design has no orchestration artifact kinds
  (`ScanPlan`/`ScanState`/… are `resiliency-skills` concepts), and validation already degrades
  gracefully for a kind without a schema (the envelope still applies). But inspecting the registry
  surfaced a *real* one-directional gap: `test_registry_governance` checked every registry kind has a
  schema file, but **not** the reverse. A schema file dropped in without a registry row would never be
  routed and would silently rot. Closed with `test_no_schema_file_is_orphaned_from_the_registry`
  (registry ↔ schema files now lock-step both ways; today 28/28, no orphans).
- **R-S2 — Publish-destination in the registry (REJECTED, with rationale).** `resiliency-skills` routes
  each kind to a per-kind `dest` subdir (`alerts/intent`, `runbooks`, `metadata`, …). sre-design does
  **not** use per-kind destinations: KB artifacts are laid out by **status** (`kb/verified`,
  `kb/needs-review`) and publish copies the whole `kb/` tree plus `projections/` (`publish/pr_builder.py`,
  `workspace/layout.py`). Adding a `dest` field to the registry would be config nothing consumes —
  dead config that invites drift. Skipped on purpose; revisit only if the publish model ever moves to
  per-kind routing.

## Bottom line

The single highest-value, lowest-risk improvement from `resiliency-skills` was its templating spine,
and this change adopts it at the right altitude: a shared sandboxed Jinja2 environment, prose rendered
from `.j2` templates, escaping centralized into one auditable module, structured/graph output kept in
Python, and the dormant `jinja2` dependency finally earning its place — all with byte-identical output
and the test suite green. The schema layer is already the stronger of the two repos; the follow-up
items are incremental polish — a documented schema contract and a tightened registry↔schema invariant —
and one (`R-S2`) was correctly rejected as not matching sre-design's status-based publish model.
