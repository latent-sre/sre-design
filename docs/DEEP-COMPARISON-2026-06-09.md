# Deep comparison (round 2): rendering, templating, and schema/YAML formatting

Date: 2026-06-09

> **Scope.** This is a focused follow-up to `docs/DEEP-COMPARISON-2026-06-07.md`. That review covered
> publish hardening, secret gates, the skill taxonomy, and role separation. It deliberately did **not**
> cover the *rendering / templating layer* or *schema/YAML/JSON formatting* — the dimensions this round
> targets, motivated by the goal of making the codebase "elite to scan and understand." The earlier
> backlog (R1–R13) is unchanged and not re-litigated here.

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
  dependency for no current consumer. (If/when manifest-hash clobber-protection lands — backlog R1 —
  revisit a dedicated canonical-dump helper, scoped to that path.)

## Schema/YAML comparison summary

Both repos use JSON Schema **draft 2020-12**, `$id` URIs, 2-space indentation, and `additionalProperties:
false` on nested objects. The substantive differences:

| Dimension | `sre-design` | `resiliency-skills` | Verdict |
|---|---|---|---|
| Governance reuse | Centralized `_envelope.schema.json`, `$ref`'d `$defs`, applied via a 2-pass validator | Governance block inlined + `$defs` duplicated in every schema | **Keep sre-design's** (DRY, one evolution point) |
| Per-kind schema scope | Only `kind` + `spec` | Whole-artifact shape | sre-design's is lighter; keep |
| Registry | `schemas/registry.yaml` (kind → schema/collectors/prompt/phase/renderer) | `registry.py` dataclass (kind → schema/dest/renderer) | sre-design's is **richer**; one gap below |
| Evidence model | Byte-grounded `evidence[]` (path/line/`excerptHash`/detector/tier) | provenance block only | **sre-design's is materially stronger** |
| Golden examples | Full envelope + evidence per kind (`tests/fixtures/golden/`) | `examples/golden/` per kind | both good |

### Remaining schema/registry recommendations (small, optional)

These are genuine but minor; none block anything and none are implemented here:

- **R-S1 — Separate control-plane kinds in `registry.yaml`.** `resiliency-skills/registry.py` cleanly
  splits deliverable `DATA_KINDS` from orchestration `CONTROL_KINDS` (`ScanPlan`, `ScanState`, …). A
  parallel `controlKinds:` section in `registry.yaml` would make "this kind has no data schema by
  design" explicit rather than implicit.
- **R-S2 — Add publish-destination metadata to the registry.** `resiliency-skills` routes
  schema→`dest`→renderer from one table; sre-design's registry already covers schema/renderer but
  publish destination lives in `publish/` code. Folding `dest` into the registry row would keep the
  "add a kind in one place" invariant true for the publish path too (complements backlog R5).
- **R-S3 — A short `schemas/README.md`** documenting the envelope-plus-spec contract and the two-pass
  validation rule, so the (correct) reason root `additionalProperties` lives only on the envelope is
  discoverable — and a future contributor doesn't "helpfully" add it per-kind. (`resiliency-skills`
  documents its governance block in `engine/schemas/_provenance.md`.)

## Bottom line

The single highest-value, lowest-risk improvement from `resiliency-skills` was its templating spine,
and this change adopts it at the right altitude: a shared sandboxed Jinja2 environment, prose rendered
from `.j2` templates, escaping centralized into one auditable module, structured/graph output kept in
Python, and the dormant `jinja2` dependency finally earning its place — all with byte-identical output
and the test suite green. The schema layer is already the stronger of the two repos; the remaining
registry/doc items (R-S1–R-S3) are incremental polish, not corrections.
