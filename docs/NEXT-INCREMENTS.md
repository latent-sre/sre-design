# Next increments — skills schema references, diagrams, AI integration, PCF facts, cross-repo estate

Proposals grounded in the codebase as of `47d43a0`. Each section states what exists today
(with `file:line` evidence), what's weak, and concrete increments ordered by effort. §6 is
the suggested sequencing. Companion docs: [`DESIGN.md`](DESIGN.md) (architecture),
[`HYBRID-PLAN.md`](HYBRID-PLAN.md) (trust tiers + roadmap),
[`SCOPE-AND-COVERAGE.md`](SCOPE-AND-COVERAGE.md) (scope matrix).

---

## 1. Schema references for skills — make the schema the single source of truth

### Today

- The registry (`src/sre_kb/schemas/registry.yaml`) maps each kind to a schema path; the
  engine loads it at validation time (`validation/structural.py:41-45`). That side is solid
  and governed (`tests/test_registry_governance.py`, `tests/test_schema_governance.py`).
- Skills reference schemas **by hand-written mirror**, not by the schema itself:
  - field docs like `.github/skills/sre-prr-review/references/prr-checks.md` and
    `sre-flow-analysis/references/flow-schema.md` restate `spec` shapes in prose;
  - skeletons like `sre-flow-analysis/templates/flow.skeleton.yaml` restate them as YAML.
- Drift detection is **one-directional**: `tests/test_skill_contract.py:76-82` proves every
  field a skill *promises* is still emitted, but nothing proves a documented field still
  exists in the schema, and nothing validates skeletons against schemas at all.
- `provenance-rules.md` is copied into ~10 skill folders (byte-identity enforced by
  `tests/test_lint_skills.py:86`, but sync is manual).
- `registry.yaml` carries a `prompt:` key per kind (~13 non-null values), but no engine code
  consumes it (`registry.py` only returns the row; live prompts are built programmatically in
  `synth/draft_prompts.py`), and only 4 files exist under `.github/prompts/`
  (`alert`, `autopilot`, `flow`, `runbook`). Keys like `resiliency`, `blast-radius`, `slo`,
  `messaging` point at nothing.

### Increments

1. **Generate skill schema references from the schemas.** Add a small renderer
   (`sre-kb render skill-refs` or a `tools/` script) that emits, per kind, a
   `references/<kind>-fields.md` and a `<kind>.skeleton.yaml` directly from
   `v1alpha1/<Kind>.schema.json` (using `title`/`description`/`enum`/`required` — enrich the
   schemas with descriptions where missing, which also improves IDE hovers). CI check =
   regenerate and `git diff --exit-code`, exactly the `make lock` pattern. This deletes the
   skeleton-drift and doc-drift classes instead of testing around them.
2. **Reverse contract test (cheap stopgap until 1).** Parse dotted `spec.*` paths quoted in
   `.github/skills/**/*.md` and assert each resolves to a property chain in that kind's
   schema. Complements `test_skill_contract.py`'s forward check. *Measured on this branch:*
   only two kind-qualified mentions exist across all skill docs (the rest are bare `spec.x`
   that regex can't attribute to a kind) — so this is folded into increment 1, where the
   generated references make the check structural instead of textual.
3. **Govern or remove the registry `prompt:` field.** Either make the engine resolve it to
   `.github/prompts/<key>.prompt.md` (and add a governance test that every non-null key has a
   file), or drop the dead keys. Today it is unvalidated metadata that reads like a contract.
4. **Single-source the shared references.** Keep one canonical
   `.github/skills/_shared/provenance-rules.md` (and `challenge-protocol.md`); have
   `tools/lint_skills.py` copy-on-sync or verify, instead of humans propagating edits ten
   times.
5. **Ship schema references *to the consumer*, not just the author.** The published PR tree
   already carries the KB YAML; add a generated `yaml.schemas` mapping
   (`.vscode/settings.json` fragment) plus `$id`s on the schemas so the target repo's editor
   — and Copilot working inside it — validates `apiVersion`/`kind` documents against the real
   JSON Schema as it types. That is the strongest form of "schema reference for skills": the
   skill no longer describes the shape; the IDE enforces it.
6. **Schema evolution story.** Before any `v1alpha1 → v1beta1` bump, support
   `deprecated: true` markers and field aliasing in the validator so a rename gets a
   soft-deprecation window. The apiVersion triangle is already lock-stepped
   (`test_schema_governance.py:53`); evolution is the missing half.

## 2. Diagram ("drawings") rendering

### Today

`render/diagrams.py` emits Mermaid sequence (`:21-38`) and topology (`:49-68`) diagrams,
sanitized through the single `mermaid()` filter (`render/templating.py:39,50-54`) and robust
to malformed specs (`tests/test_diagrams.py:33-42`). Limitations: no legends; node shapes
(`_SHAPE`, `diagrams.py:41-46`) carry semantics nobody is told about; every non-HTTP/DB/broker
step collapses to a generic `Dependency` participant (`:13-18`); no criticality/data-loss
visual encoding; no grouping; output is bare `.mmd` that GitHub won't render inline.

### Increments

1. **Legends + engine-controlled styling.** *Partially done on this branch:* topology nodes
   are styled per type from a fixed engine `classDef` vocabulary (unknown types render
   unstyled — scanned strings can never reach a style line), with a legend in the markdown
   wrapper. Still open: criticality-tier coloring and data-loss edge styling from
   `Criticality`/`BlastRadius` artifact joins.
2. **Render GitHub-native wrappers** — **done on this branch.** Every flow and topology
   diagram also emits `diagrams/<name>.md` with a fenced ```mermaid block (plus the topology
   legend), so PRs and the published KB render drawings inline with zero tooling.
3. **Promote known services to named participants.** In sequence diagrams, when a step's
   target matches a `config.client` name (or, after §5.1, a resolved service), render it as a
   named participant instead of the `Dependency` catch-all.
4. **Estate subgraphs.** Group the estate topology with `subgraph` per service vs. a shared
   "co-tenancy" cluster; once §4.3 lands org/space facts, group by space — that is the drawing
   that makes blast radius legible to an app team.
5. **Architecture context diagram.** A C4-style context view rendered from the
   `Architecture` artifact (components + patterns) — same Mermaid pipeline, new projector.
6. **(Tier-B, cheap) Diagram narration.** Add a worklist task where the LLM writes the
   one-paragraph "what this drawing shows / what to worry about" caption from the artifact
   JSON (closed-world input, pointer-generator rules, advisory rendering). Drawings are the
   one projection with no prose today.

## 3. AI integration after the "LLM gate"

Clarification first: the gate was not dropped — it was **renamed and absorbed**. The
discover/confirm loops described as "the LLM gate" in `SCOPE-AND-COVERAGE.md` §6 live on as
`sre-kb gap-finder` (Tier-B discover, `collectors/llm/gap_finder.py`) and the confirm
precision gate (`pipeline/confirm.py`), both behind the model-free-by-default `LLMProvider`
seam (`llm/provider.py:47-62`). "Integrate AI more" therefore means widening what flows
through that seam, not rebuilding trust machinery.

### Increments

1. **Land a programmatic provider.** `VertexProvider` is a named, deferred slot
   (`llm/provider.py:100-118`) with a written business case
   ([`VERTEX-LLM-PROVIDER-CASE.md`](VERTEX-LLM-PROVIDER-CASE.md)). Approving it (or any
   sanctioned CLI via `SubprocessProvider`) unlocks scheduled `autopilot` runs in CI,
   estate-wide fan-out, and drift-triggered re-scans — with `CachingProvider`
   (`provider.py:121-150`) keeping CI replayable. This is the single highest-leverage AI
   item; everything below rides on the same worklist.
2. **New Tier-B worklist tasks** (each reuses the existing untrusted-framed context packs and
   re-grounding):
   - *PCF deployment review* — judgment calls over `pcf.app` facts: single-instance critical
     app, `health-check-type: port` on an HTTP service, missing `disk_quota`, env-var config
     that belongs in a service binding (pairs with §4).
   - *Cross-repo edge confirmation* — ambiguous estate matches (IP baseUrls, aliased
     hostnames) go to the confirm loop instead of being guessed (pairs with §5.6).
   - *Diagram narration* (§2.6).
3. **Close the graduation flywheel.** `pipeline/confirm.py:375-418` already tallies
   confirmations and `graduation_draft.py` drafts collectors; add the stats trigger — when a
   category's confirmed share crosses a threshold across N services, emit a "time to graduate
   this to Tier-A" finding automatically. That is how the AI surface *shrinks* over time, the
   plan's stated goal.
4. **Invariants to hold** (unchanged): pointer-generator never fact-source; downgrade-only
   gating; every Tier-B output re-grounded at cited bytes; target content fenced as untrusted.

## 4. PCF facts for an app-focused team

### Today

Collection is **static-manifest-only** (`collectors/common/manifest_pcf.py:10-62`): name,
instances, memory, disk, stack, buildpacks, routes, service *names*, the literal `env:` map,
command, health check. Meanwhile `SCOPE-AND-COVERAGE.md` §2 claims "service bindings (VCAP)"
in scope — a real scope/implementation mismatch — and two schema landing zones sit empty:
`Topology.spec.pcfSpaces` (hardcoded `[]`, `estate/topology.py:42`) and all of
`ConfigManagement` (sources/profiles/refreshScope/properties).

The constraint that matters: the team is app-focused, so every source below is something a
developer already has in-repo or can export with space-developer rights — no platform API
integration required.

### Increments (by source, increasing effort)

1. **Finish the manifest we already parse.** `processes:` (web vs worker instance counts —
   today a worker-bearing app misreports as a single web process), `sidecars:`, `services:`
   entries as maps (v3 binding `parameters:`), `no-route`/`random-route`, and **`vars.yml` /
   `manifest-<env>.yml` variants** — resolving `((var))` interpolation per environment gives
   the KB an environments dimension for free. All static YAML, all Tier-A.
2. **Mine app config as PCF evidence.** Spring `application-cloud.yml` / spring.cloud.*
   properties and Steeltoe connector config encode binding expectations and config sources;
   route them into the unpopulated `ConfigManagement` artifact. Collector exists
   (`java_spring/config_props.py`) — it needs a ConfigManagement synthesizer, not new parsing.
3. **A redacted `cf env` snapshot convention — `.sre/cf-env.json`.** Developers can run
   `cf env <app>` themselves. Define a checked-in, *credential-stripped* shape: from
   `VCAP_SERVICES` keep label/plan/tags/name per binding (never `credentials`); from
   `VCAP_APPLICATION` keep `organization_name`/`space_name`. This single file:
   - upgrades `Dependency` artifacts from bare names to typed, planned services;
   - finally populates `Topology.pcfSpaces` and gives estate diagrams real grouping (§2.4);
   - distinguishes managed vs user-provided services.
   Guardrails: the existing fail-closed secret-scan gate and `detect-secrets` baseline cover
   the file; stamp snapshot-derived facts with a freshness/source marker (they drift from
   live state — which is exactly what `sre-kb diff` is for). The gap-finder can flag a
   missing or stale snapshot as a finding, making adoption self-propelling.
4. **Pipeline files as deployment evidence.** Parse `cf push` invocations out of checked-in
   CI definitions (GitHub workflows, Concourse, etc.) → org/space/manifest per environment,
   and populate the `DeliveryPipeline` kind, which today has a schema but no collector.
5. **Fix the scope statement either way.** If 3 lands, `SCOPE-AND-COVERAGE.md` §2 becomes
   true; if it's rejected, reword "service bindings (VCAP)" to "declared service names
   (manifest)". Platform-state sources (autoscaler API, network policies, broker SLAs) stay
   explicitly out of scope — listed, so the boundary is a decision rather than an accident.

## 5. Cross-repo linkage — relating software across repositories

### Today

Exactly one deterministic cross-repo mechanism exists: **shared PCF service bindings** →
co-tenancy `BlastRadius` (`estate/topology.py:25-29, 51-73`). HTTP client config is collected
(`config.client` with `baseUrl`, `java_spring/config_props.py:34-50`) but edges terminate at a
synthetic node named after the client key (`estate/topology.py:30-33`) — the `baseUrl` is
never matched against another scanned service's routes. Messaging topics are never joined
across repos. There is no shared-library lineage and no frontend→backend linkage.

The encouraging part: for the first three increments below, **both sides' facts are already
collected** — these are joins in `build_estate`, not new collectors.

### Increments

1. **Route ↔ baseUrl resolution** — **done on this branch.** `build_estate` matches each
   `config.client.baseUrl` hostname against every scanned service's `pcf.app.routes`; a hit
   becomes a real `service —calls→ service` edge, a miss stays the `external` node
   (`estate/topology.py`).
2. **Messaging topic join** — **done on this branch.** `message.egress.channel` and
   `message.consumer.channel` merge across services into shared `topic` nodes with
   publishes/consumes edges (estate and single-service Topology both), so "who consumes
   `order.created`?" is answerable from the graph.
3. **Shared-library lineage.** `tech.dependency` facts already come from
   pom.xml/csproj/package.json. Join on a configurable internal-namespace allowlist
   (e.g. `com.acme.*`, `@acme/*`) → `service —uses-library→ lib` edges, plus a **version-skew
   finding** when two services pin different versions of the same internal library (the
   "margin/shared libraries" picture: which repos a library change blasts into).
4. **SPA → backend edges.** Extend the Node collector to read what frontends already declare:
   `proxy` in package.json, vite/webpack devServer proxies, `.env` `*_API_URL` vars, axios
   `baseURL` constants — emit them as `config.client`-equivalent facts so SPAs flow through
   increment 1 unchanged. Add a `frontend` node type to `Topology` + `_SHAPE`. A SPA repo and
   its API repo then connect with zero manual declaration.
5. **OpenAPI contract join.** Match a provider's spec endpoints (`api.spec.endpoint`) against
   consumers' `http.egress` paths → contract-backed edges; estate-level blast radius for a
   breaking change becomes "this `api.contract.change` impacts services X, Y" instead of a
   single-repo finding.
6. **Tier-B confirm for ambiguous matches.** IP-literal baseUrls, aliased hostnames, and
   wildcard routes don't get guessed — they become confirm-worklist items (the existing
   precision gate, §3.2), keeping the estate graph downgrade-only honest.
7. **Transitive impact.** With real edges from 1–2, fold the estate graph (bounded depth) so
   `BlastRadius.impactedServices` includes A→B→C reach, not just direct neighbors.

## 6. Suggested sequencing

| Order | Items | Why first |
|---|---|---|
| Quick wins (each ≤ a day, pure joins/tests) | §1.2, §1.3, §5.1, §5.2, §2.1, §2.2, §4.1 | Facts/tests already exist; immediate drift-class kills and visible estate/diagram payoff |
| Medium | §1.1, §1.4, §4.2, §5.3, §2.3, §2.4, §3.3 | New small renderers/synthesizers, no new trust surface |
| Needs a decision | §3.1 (provider approval), §4.3 (snapshot convention + redaction shape), §1.5 (publish-tree addition) | Org sign-off or convention design before code |
| Larger | §5.4, §5.5, §2.5, §3.2, §5.7, §1.6 | New collectors/projectors; build on the above |

## 7. Empty-artifact audit

A sweep of every kind's emit path against its schema found three classes of "empty".

**Never emitted by the engine** (schema + registry row + golden fixture, no emit site) — all
three now emit on this branch:

| Kind | How it fills now |
|---|---|
| `DeliveryPipeline` | new `common.delivery_pipeline` collector parses `.github/workflows/*.yml` (jobs → stages, push branches, `cf push` detection) — §4.4's first half; Concourse/other CI systems remain open |
| `SecurityPosture` | rolled up deterministically from byte-grounded facts: security/oauth2 deps → `authn`, new `@PreAuthorize`/`@Secured`/`@RolesAllowed` detection → `authz`, actuator exposure → control or `openRisks` (a `*` exposure is a risk); judgment calls stay with the `sre-security-posture` skill |
| `Topology` (single-service) | emitted per run from binding/client facts (`synth/inventory.py`), rendered via a registry `topology` renderer to `diagrams/<service>-topology.mmd` |

**Hardcoded-empty fields where the engine already had the knowledge** — fixed on this branch:

- Estate co-tenancy `BlastRadius.impactedFlows` was `[]`; now joined from each tenant's
  `flow.flow` sinks (direct slug match, or the sole binding of the sink's type)
  (`estate/topology.py:_impacted_flows`).
- `Interface.endpoints[].idempotent`/`retrySafe` were always `null`; now derived — safe
  methods by HTTP semantics, mutating methods via the same Tier-A `idempotency` signature the
  gap collector fires, so the Interface and `missing-idempotency` gaps cannot disagree
  (`synth/inventory.py`).
- `ServiceCatalogEntry.providesApis` carried only the first flow's trigger path; now every
  detected `rest.endpoint` path (`synth/scaffold.py`).
- `ConfigManagement.sources` was a constant list and `refreshScope` a hardcoded `False`; now
  the files the config facts actually cite (+ `pcf-manifest-env` only when an env block
  exists) and a real `@RefreshScope` detection (`config.refreshscope` fact,
  `collectors/java_spring/annotations.py`).
- Datastore `BlastRadius.stateful.dataLossRisk` was hardcoded `False`; the missing upstream
  signal landed too — a `save()` inside a logged-and-swallowed catch now marks the flow's
  db-write step lossy (`flow_builder.py`), and the BlastRadius derives from it
  (`synth/scaffold.py:_lossy_sink`).

**Empty by design** (not gaps): `Alert.sloRef: null` on log-pattern alerts (no SLO exists
yet), `ReadinessScore.evidence: []` (a roll-up, not a source fact), `crossRefs: []` outside
the Flow→Alert→Runbook→BlastRadius chain, and `metadata.labels`/`annotations` (free envelope
slots — candidates for run id / criticality tier / org-space once §4.3 lands).

Still open from the audit: `Topology.pcfSpaces` (waits on §4.3's org/space source), non-GitHub
CI systems for `DeliveryPipeline`, and .NET parity for the new lossy-save, authz, and
refresh-scope signals.

The through-line: every increment keeps the engine's core contract — deterministic facts with
byte provenance, LLM as pointer-generator behind the seam, downgrade-only gating — and most of
the cross-repo and PCF picture turns out to be *joins over facts already collected*, which is
the cheapest kind of new capability this codebase can buy.
