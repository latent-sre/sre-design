# LLM-first design & `resiliency-skills` deep review

> **What this doc is.** The design and plan for taking `sre-design` **LLM-first** and adopting the
> neutral-artifact model from its sibling repo [`latent-sre/resiliency-skills`](https://github.com/latent-sre/resiliency-skills).
> It also persists the deep review of that sibling suite so a fresh session need not re-clone or
> re-derive it. Read this file first, then `docs/SCOPE-AND-COVERAGE.md`, `docs/NEXT-INCREMENTS.md` §5,
> and `src/sre_kb/render/alerts.py`.

Reference snapshot: `resiliency-skills` @ `04e220e87d2e7d55296c3787bb11a645bfe0926e`.

## 1. The direction, in one paragraph

The LLM (Copilot / Claude in the IDE) reads the target's code **across files** and emits the SRE
analysis **directly** — dependencies, callers, resiliency gaps, alerts — as neutral artifacts carrying
a governance block. The design **drops the grounding *gate*** (a deterministic engine that re-derives
every fact and downgrades the LLM to `needs-review`). `path:line` citations stay for traceability, but
nothing second-guesses the model by construction.

**The engine ENHANCES, it does not GATE.** The `sre-kb` engine still runs — to cross-check, enrich,
and render — but as a *tool the analyst calls*, not a judge that overrules it. An engine confirmation
**raises** a finding's confidence and lends it a byte-grounded `path:line`; an engine miss does **not**
erase a finding (the AST model is per-file and misses cross-file facts the LLM can see) — the
disagreement is recorded for a human. See `.github/skills/_shared/challenge-protocol.md`.

## 2. Deep review of `resiliency-skills` (the LLM-first ancestor)

`resiliency-skills` is the suite `sre-design` forked from *before* it grew the AST engine and the
re-grounding gate. Because it never had that gate, it is already the model this design pivots toward.

**Design motto: "thin skills, fat config, deterministic transforms."** Two surfaces, one hard boundary:

- **LLM skills** (thin prose `SKILL.md`) do *inference only* and emit **neutral artifacts** — field
  names and shapes, never copied values, never tool query syntax. 18 skills, one artifact `kind` each.
- **The `latent-sre` Python engine** does *only* deterministic, security-critical transforms: schema
  validation, secret redaction, per-tool alert/runbook/dashboard rendering, repo scaffolding/assembly,
  dependency-graph drawing, fan-out discovery. **It does zero code parsing** (no AST/call-graph) —
  all code comprehension is the LLM's unaided job.
- **Two roles never share a context:** a read-only *scan role* (no creds, target = untrusted data) and
  a *publish role* (CI, credential scoped to `SRE-*`). This contains prompt-injection from a hostile
  target repo, independent of any grounding gate — worth keeping.

Every artifact carries a **governance block**: `provenance {repo, commit, scanDate, skill}`,
`ownership: app|platform|shared`, `confidence: high|medium|low`, `needs-human-review: true`, and
`unverified-against-live: true` for anything not checked against a live system.

### 2.1 The 18-skill catalog (families)

- **map-\*** (structural discovery): `map-dependencies`, `map-messaging`, `map-api-contracts`,
  `map-architecture`, `map-infrastructure`, `map-jobs`, `map-delivery`, `map-pcf-application`.
- **assess-\*** (posture/gaps): `assess-resiliency`, `assess-criticality-and-data`, `assess-logging`,
  `assess-observability-coverage`, `assess-tech-stack`.
- **generate-\*** (neutral deliverables the engine renders): `generate-slos`, `generate-alerts`,
  `generate-dashboards`, `generate-runbooks`.
- **publish-sre-repo** (the CI publish role).

Orchestrated by the read-only `sre-analyst` agent through phases **classify → map → assess → generate**,
checkpointing per skill to `.sre-scan/<service>/scan-state.yaml`.

### 2.2 The two standouts to adopt

- **The `AlertIntent` model** (`docs/alert-intent-model.md`): skills emit one neutral intent
  (`signal` + `condition` + `burnRate` + `severity` + `class: symptom|cause` + runbook/SLO links); the
  engine renders it to Prometheus/Grafana/Splunk/Wavefront/AppDynamics/ThousandEyes. Severity is
  **floored by the service's criticality tier** (raise-only), and absent connection fields render as
  loud `REPLACE_ME__*` sentinels. *Caveat:* `signal.query` is emitted verbatim to every target today —
  true cross-dialect synthesis (one signal → valid PromQL *and* SPL) is documented future work.
- **`assess-resiliency`'s structured gaps**: `{pattern, target, severity, evidence}` joined to a
  dependency by `target`, with the rule *"a pattern without its load-bearing params is itself a gap"*
  (a `retry` with no backoff, a `timeout` with no `timeoutMs`).

### 2.3 The confirmed gap in BOTH repos: "who calls the api"

No skill in either suite maps **inbound callers / reverse dependencies / a consumer graph**. In
`resiliency-skills`, `map-dependencies`' `direction: upstream|downstream` is a *data-flow* qualifier on
the service's **own** dependencies — both rendered as edges *from* the service (`engine/src/latent_sre/
mermaid.py`). It is not a caller axis. A repo-wide grep for `caller|inbound|reverse dep|consumer graph|
called by` returns nothing. A single-repo scan structurally cannot produce it; it needs cross-repo /
fleet correlation. **This is the novel capability to build: `map-callers`.** In `sre-design` the
raw material already exists — `src/sre_kb/estate/topology.py` reverses resolved `calls` edges into
`callers_of` and walks transitive callers; it just is not surfaced as a first-class deliverable.

## 3. What `sre-design` already has (so the port lands mostly at the skills layer)

- **The tool-neutral alert intent + per-backend adapters** live in `src/sre_kb/render/alerts.py`
  (Prometheus/Grafana/Splunk/Wavefront/AppDynamics/ThousandEyes, `REPLACE_ME__` sentinels), with the
  **tier→severity floor** (`effective_severity`, `TIER_SEVERITY_FLOOR`, commented "idea adopted from
  resiliency-skills") and `rendered_targets`.
- **The central taxonomy** `src/sre_kb/schemas/taxonomy.yaml` already reconciles `sev1..sev4`
  (`severity_aliases`) onto the canonical scale, plus `ownership`, `criticality_tier`,
  `data_classification`. Reuse it; do **not** duplicate a `lib/taxonomy.yaml`.

So the port completes at the **skills + shared-config + docs** layer (LLM-first neutral-artifact
authoring + the governance block), reusing the engine's existing render half.

## 4. The plan (deliverables)

1. **Shared contract.** Rewrite `.github/skills/_shared/provenance-rules.md` → "Evidence & the
   governance block" and `challenge-protocol.md` → "Self-review" (engine enhances, not gates); propagate
   the bundled copies with `python tools/lint_skills.py --sync`.
2. **AlertIntent adoption.** Modernize `generate-alerts` to emit the neutral intent (reusing
   `render/alerts.py`), with the governance block, LLM-first.
3. **`map-dependencies`** (outbound: HTTP/gRPC/db/queue/cache/SDK/libs, cross-file, resilience posture
   + failure mode).
4. **`map-callers`** (inbound / who-calls — the novel gap; see §6) + an **`sre-dependency-analyst`**
   orchestrator agent.
5. **Modernize every existing `sre-*`/`map-*`/`generate-*` skill + the 3 agents** onto the
   neutral-artifact + governance + LLM-first shape (drop pointer-generator / engine-re-grounds /
   needs-review-gate framing; keep `path:line` citations).

Each is a focused, CI-green commit.

## 5. Use the engine to ENHANCE (the `sre-kb` calls to weave into skills/agent)

- `sre-kb run --target <repo> --to-stage scaffold` (or `validate`) → deterministic AST facts
  (dependencies, egress, resiliency signatures). Where the engine independently confirms an LLM
  finding, **raise** confidence and cite its byte-grounded `path:line`; where they disagree, surface
  a note for a human. The engine never lowers LLM confidence.
- `sre-kb findings --run <id>` → ranked, evidence-linked risks to fold in.
- `sre-kb estate --target A --target B …` → the **fleet caller-graph** + co-tenancy blast radius —
  this is how `map-callers` answers "who calls me" across your repos.
- `src/sre_kb/render/alerts.py` (via the scaffolder) → render alert intents to the six tools.

## 6. `map-callers` design (the novel capability)

Two scopes, both LLM-first, both engine-enhanceable:

1. **Internal call graph (within the repo).** Follow calls across files to answer "who invokes this
   endpoint handler / service method / exported function?" — the change-impact / blast-radius view. The
   LLM does the cross-file traversal the per-file AST model cannot.
2. **Cross-repo consumers (fleet).** Find *other* services that call this one: sibling repos' HTTP
   client code, config base URLs that resolve to this service's routes, OpenAPI/consumer contracts,
   message topics consumed. Enhance with `sre-kb estate` (which already resolves route↔baseUrl edges
   and reverses them).

**Honesty rule:** true external callers cannot be known from the service's own code alone. Say so —
list the internal callers + declared/derivable consumers, mark the rest `not-observable-from-repo`
+ `confidence: low`, and point at the fleet scan or runtime signals (traces / gateway logs) as the
way to complete it. Never fabricate a caller.

## 7. CI guardrails (keep green: `make cov`, `make lint`)

- Every skill dir appears exactly once in `.github/skills/pipeline.yaml`.
- Frontmatter: `name` == dir name; `description` 10..1024 chars; `allowed-tools` an inline list from
  `{codebase, search, editFiles, runCommands}`; a `version` only under `metadata`; `SKILL.md` body
  < 500 lines.
- `sre-incident-response` stays read-only (no `editFiles`/`runCommands`). Keep the skills
  `sre-flow-analysis`, `sre-prr-review`, `sre-blast-radius`, `sre-estate`, `sre-incident-response`.
- All relative markdown links resolve; the two `_shared` files stay byte-identical across their bundled
  copies (edit the canonical file, then `python tools/lint_skills.py --sync`).
- Don't change dependencies (no `requirements.lock` churn); commit no secrets.

## 8. Cold-start prompt (paste into a fresh session on this repo)

```
Read docs/LLM-FIRST-PORT.md first — the design + plan. Take sre-design LLM-first: the LLM reads code
across files and emits the SRE analysis directly (neutral artifacts + governance block, path:line
citations, NO re-grounding gate) and RUNS the sre-kb engine to ENHANCE findings (cross-check, enrich,
render) without letting it override the model. Execute the deliverables in §4: rewrite the _shared
contract; adopt the AlertIntent model in generate-alerts (reuse src/sre_kb/render/alerts.py); add
map-dependencies (outbound) and the novel map-callers (inbound/who-calls, §6) plus an
sre-dependency-analyst agent; then modernize every existing sre-*/map-*/generate- skill + the 3 agents
(sre-analyst, sre-oncall, sre-target-scan) onto the neutral-artifact + governance shape. Reuse the
engine's existing render adapters and taxonomy (§3). Keep CI green (§7). Cut a feature branch from
origin/main; Conventional Commits. To read the reference suite, add_repo latent-sre/resiliency-skills
and check out 04e220e.
```
