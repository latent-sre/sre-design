# Deep comparison: sre-design vs resiliency-skills

Date: 2026-06-07

> **Update — reconciled with `main` after PRs #28 and #30 (both merged).** This review was written
> against an earlier `origin/main` and excluded `HYBRID-PLAN.md`, so parts of its backlog are now
> stale:
>
> **Landed in #28** (publish hardening): **R1** no-clobber assembly — engine-owned in
> `publish/manifest.py` (`.proposed/` routing, `_claim_*` collision detection, orphan pruning); #28
> made the forge the sole merge authority. **R2** fail-closed secret gate (scan-then-block; redaction
> only on `--allow-secrets`; entropy/value-shape; expanded provider classes). **R3** generated-repo
> hardening (vendored schemas + validate CI + CODEOWNERS sentinel + PR template + `.sre/version`, at
> the published repo **root**). **R4** read-only `sre-target-scan` agent. The "Publish assembly" /
> "Missing no-clobber" rows below **under-credited R1** — the no-clobber lives in
> `publish/forge/github.py`, not `pr_builder.py`.
>
> **Landed in #30** (render breadth): **R10** Grafana + ThousandEyes render paths — 6/6 alert backends
> (Grafana reuses the deterministic Prometheus PromQL over a datasource; ThousandEyes is an
> honestly-labelled synthetic rule) plus Grafana/Wavefront dashboard panels, with `REPLACE_ME__`
> sentinels and parse tests.
>
> Also: schemas **and** config now ship as package data (self-contained wheel), meeting R9's
> offline-wheel precondition. **Still open:** R5 (declarative registry), R6/R7 (Tier-B skill pipeline +
> first skills), R8 (service discovery / fan-out / resume), R9 hash-pinned locks + R11 independent
> second gate (both gate a live `--no-dry-run` publish). See `HYBRID-PLAN.md` §9.3 / §9.7 for the
> reconciled forward order.

## Evidence boundary

Reviewed refs:

- `latent-sre/sre-design` `origin/main`: `fa484fe0c74e125efbad9754caa4db0f9837fefe`
- `latent-sre/resiliency-skills` `origin/main`: `f99e02811036d6b06c3d063615713d4eed97c18e`

Explicitly excluded from this review:

- `docs/HYBRID-PLAN.md`
- `docs/PHASE-4-GAP-FINDER.md`
- `docs/REASSESSMENT*.md`

Validation run:

- `sre-design`: `.venv\Scripts\python.exe -m pytest -q` -> `253 passed`
- `sre-design`: `.venv\Scripts\python.exe tools\lint_skills.py` -> `lint-skills: ok`
- `resiliency-skills`: `F:\repos\sre-design\.venv\Scripts\python.exe tools\lint_skills.py` -> `lint-skills: ok (18 skill(s))`
- `resiliency-skills` engine tests were attempted but not executed in a prepared engine environment; collection failed because the current `sre-design` venv does not include `ruamel.yaml`.

## Executive recommendation

Do not lift and shift `resiliency-skills` wholesale. Keep `sre-design` as the system of record because its byte-grounded AST extraction, path/line/hash evidence model, status-aware validation, and Tier-A/Tier-B trust spine are stronger foundations for authoritative SRE findings.

Do refactor/adapt aggressively from `resiliency-skills` in two areas:

1. Publish-path hardening: no-clobber assembly, output collision detection, orphan pruning, vendored schemas in generated repos, CODEOWNERS/PR-template sentinels, generated repo CI, and stronger fail-closed secret scanning.
2. Skill-suite breadth: use the external 18-skill pipeline as the Tier-B recall and reviewer-guidance taxonomy, mapped onto `sre-design` kinds instead of adopting the external schemas as-is.

The directional pivot is modest but important: make `sre-design` a stronger deterministic engine with a richer, read-only Tier-B scan surface. The LLM should improve recall, prioritization, contradictions, and human review prompts. It should not become an authority source, publish role, severity source, or query generator.

## Capability comparison

| Area | `sre-design` current state | `resiliency-skills` current state | Recommendation |
|---|---|---|---|
| Core evidence model | Strong. Artifacts use shared envelope with evidence, excerpt hashes, status, confidence, and trust tiers. | Weaker for authoritative claims. Uses governance block, human-review flag, and provenance metadata, but not the same byte-hash claim validation. | Keep `sre-design` model. Map external concepts into the existing envelope. |
| Extraction | Strong. Java/Spring, .NET/Steeltoe, and Python/FastAPI collectors use deterministic facts and tree-sitter code model. | Skill-first. Copilot reads target repo and emits neutral artifacts. Engine mostly validates/renders/publishes. | Keep deterministic collectors for Tier-A. Add skill-only recall as Tier-B. |
| Skill inventory | Narrow: `sre-flow-analysis`, `sre-criticality`, `sre-gap-finder`. | Broad: 18 skills across classify, map, assess, generate, publish. | Adapt the taxonomy. Do not adopt the publish skill as an agent capability. |
| Orchestration | Local agent can run commands and edit artifacts. Engine runs scan/scaffold/validate/render/publish. | Clear scan role vs publish role. Scan role is read-only, no terminal/network/write token. Publish role is CI. | Split modes: keep developer-agent loop for this repo, add target-scan role with read-only constraints. |
| Publish assembly | Stages PR tree, secret redacts, gate checks, forge allowlist, artifact cap. Missing no-clobber/reassembly semantics. | Strong deterministic `assemble`: no clobber, collisions fail, orphans pruned, vendored schemas, generated CI. | Adapt external `assemble` behaviors into `sre_kb.publish`. |
| Secret handling | Good baseline. Redacts then gates common patterns. | Stronger fail-closed posture: known patterns, entropy, secret-ish value shapes, UTF-16/latin-1 text handling, allowlist, redacted findings. | Adapt stronger scanner and block publish on detected real secrets before auto-scrub. |
| Generated repo hardening | Backstage-ish PR tree with review and findings. | Hardened repo skeleton: vendored schemas, own CI, CODEOWNERS sentinel, PR template, Renovate/offline story. | Adapt generated repo hardening. |
| Schema strategy | Rich `sre.kb/v1alpha1` kind catalog. External AlertIntent/Dashboard concepts already partly absorbed. | Simpler `sre.latent-sre/v1` artifacts, good for scan handoff and render adapters. | Do not fork schema lineage. Use a mapping layer from external skill outputs to local kinds. |
| Supply chain | Basic Python deps and CI matrix. No lock/hash/offline package story. | Hash-pinned lock files, offline bundle, generated repo versioning story. | Adapt for enterprise/on-prem readiness. |

## Master SDE pass

1. Keep the `sre-design` deterministic spine.

   The local codebase has a cleaner authority boundary for real findings: collectors emit normalized facts, artifacts cite exact evidence, validation recomputes evidence, and tests cover adversarial cases. The external engine is useful, but it is primarily a deterministic transform/publish package around LLM-authored neutral artifacts. Replacing `sre-design` with that would lose the main engineering advantage.

2. Refactor publish assembly around an explicit manifest.

   `resiliency-skills/engine/src/latent_sre/assemble.py` is the best lift candidate. It stages outputs per artifact, detects collisions before merge, preserves human edits by comparing normalized hashes from `.sre/manifest.yaml`, routes AI proposals to `.proposed/`, and prunes AI-owned orphans. `sre-design/src/sre_kb/publish/pr_builder.py` currently rebuilds the PR tree by deleting the service directory first. That is acceptable for a dry-run staging tree, but it is not enough for repeated assembly into a living `SRE-<service>` repo.

3. Upgrade registry consistency.

   `resiliency-skills/engine/src/latent_sre/registry.py` uses one declarative `ArtifactKind` table for schema, destination, and renderer. `sre-design/schemas/registry.yaml` is richer, but render/publish routing is spread across scaffold/render/publish code. Keep the richer registry, but extend it with publish destination and renderer metadata so adding a kind cannot silently skip generated repo validation or publishing.

4. Avoid direct schema lift-and-shift.

   External schemas use `apiVersion: sre.latent-sre/v1`, top-level `ownership`, `confidence: high|medium|low`, and `needs-human-review: true`. Local schemas use `sre.kb/v1alpha1`, shared envelope, numeric confidence, `status`, crossRefs, and `source_tier`. Direct adoption would create two incompatible artifact families. Adapt external fields into local metadata/spec/status instead.

5. Add supply-chain discipline without package churn.

   External `engine/pyproject.toml`, `requirements.lock`, `requirements-dev.lock`, and `scripts/build-offline.sh` are strong references for hash-pinned installs and air-gapped PCF runners. Adopt the lock/offline pattern in `sre-design`, but keep the package name and source layout unless there is a separate distribution reason to split a `latent-sre` package.

6. Use checked-in tests as adoption templates.

   External `engine/tests/test_assemble.py` is unusually high-value: no-clobber, CODEOWNERS preservation, duplicate output paths, malformed human edits, orphan pruning, severity floors, and hostile render targets are all pinned. These should become local tests before or alongside implementation.

## Master SRE pass

1. Strengthen the scan/publish credential boundary.

   The external scan-role model is safer for hostile target repositories: read-only, no terminal, no network, no write credential, and target content is always data. Local `.github/agents/sre-analyst.agent.md` currently grants `editFiles` and `runCommands` so Copilot can run the closed loop. That is productive for development, but too much authority for a target-repo scan role. Add a separate target-scan agent profile that cannot publish and cannot execute target-provided commands.

2. Change secret handling from "scrub then pass" to fail-closed for publish.

   Local `assemble_pr` calls `redact_tree(tree)` and then `enforce_secret_gate(tree)`. This prevents leaks, but it can hide the fact that a generated artifact contained a real secret. External `redact.py` treats any plausible secret as a blocking finding and never echoes the full secret. Recommended behavior: scan first, block if real findings exist, produce redacted preview findings for humans, and reserve in-place redaction for explicit local preview modes.

3. Vendor schemas into generated repos.

   `resiliency-skills` generated repos validate against the schemas they were born with under `.sre/schemas`. This avoids a bad failure mode where central `main` changes schemas and suddenly old service KB repos cannot merge routine edits. `sre-design` should adopt this for the published `SRE-<service>` tree.

4. Add generated repo CI and CODEOWNERS sentinels.

   External generated CI fails if `.github/CODEOWNERS` still contains `REPLACE_ME__owning_team`, then validates artifacts and runs two secret gates. This is operationally important. A generated knowledge repo without enforced owners and local validation will rot quickly.

5. Expand render targets only behind honest adapter semantics.

   Local alert adapters already avoid pretending every backend can express every intent. Keep that discipline. Add Grafana and ThousandEyes only where the engine can emit honest sentinel-backed outputs. Do not let Tier-B write SPL/WQL/PromQL or dashboard JSON directly.

6. Add service fan-out planning.

   Local publish has an artifact-count cap. External `app-names`/`plan` adds service discovery, per-service scan plans, fan-out cap, and resumability. This is the right operational control for monorepos: block runaway service creation before artifacts exist.

## Architect pass

1. The right architecture is hybrid by responsibility, not by artifact lineage.

   `sre-design` should remain the authority engine. `resiliency-skills` should become a source of patterns for scan orchestration, skill taxonomy, and publish hardening. A direct engine merge would produce duplicated schemas, two CLIs, and unclear ownership of validation truth.

2. Tier-B should become a broad recall layer.

   The external skill inventory is valuable because it names the missing recall surfaces: APIs, messaging, delivery, jobs, observability coverage, SLOs, dashboards, logging, infrastructure, and architecture. Those skills should produce proposals or reviewer worklists that flow through local validators. They should not write verified artifacts directly.

3. Deterministic promotion is the north star.

   If a Tier-B skill repeatedly finds the same class of real issue, promote that category into deterministic signatures, collectors, and tests. The LLM is a scout; the engine is the judge.

4. Make role separation visible in product behavior.

   There should be two obvious modes:

   - Developer mode for maintaining `sre-design`, allowed to run tests and edit code.
   - Target scan mode for untrusted service repos, read-only and no publish authority.

   This distinction should be reflected in Copilot instructions, agent files, CLI docs, and generated repo templates.

5. The recommended pivot is sequencing, not mission.

   Prioritize publish hardening and role boundary before adding many new Tier-B skills. A larger skill suite without a safer publish path increases review load and operational risk. The order should be: harden publish, define Tier-B ingestion contract, then expand skills.

## Recommendation backlog

| ID | Priority | Recommendation | Adoption | Effort | Risk | Acceptance criteria |
|---|---|---|---|---|---|---|
| R1 | P0 | Add manifest-backed no-clobber assembly for published `SRE-<service>` trees. | Adapt | M | Medium | Re-scan preserves human edits, writes AI changes to `.proposed/`, detects duplicate outputs, prunes AI-owned orphans, preserves edited orphans. |
| R2 | P0 | Replace publish secret flow with fail-closed pre-publish detection plus redacted findings. | Adapt | M | Medium | A planted AWS/GitHub/JWT/URI/high-entropy/value-shape secret blocks publish before output is accepted; findings never reveal full secret. |
| R3 | P0 | Generate repo hardening: vendored schemas, validate workflow, CODEOWNERS sentinel, PR template, `.sre/version`. | Adapt | M | Low | Generated repo has self-contained validation; CI fails on unreplaced owner sentinel; validates against vendored schemas. |
| R4 | P0 | Define target-scan agent separate from developer agent. | Adapt | S | Low | Target scan profile has no terminal, network, publish, or target-write authority; developer profile remains available for repo maintenance. |
| R5 | P1 | Extend `schemas/registry.yaml` or a companion registry with publish destination and renderer metadata. | Adapt | M | Medium | A new kind can be added once and is included in validation, render, and publish tests. |
| R6 | P1 | Add a canonical Tier-B skill pipeline manifest and lint that every local skill appears exactly once. | Adapt | S | Low | Skill pipeline covers classify/map/assess/generate phases; lint fails on missing or duplicate skills. |
| R7 | P1 | Add first Tier-B skills: `map-api-contracts`, `map-messaging`, `assess-observability-coverage`, `generate-slos`, `generate-dashboards`. | Adapt | M/L | Medium | Each emits proposals/worklist entries with cited anchors; nothing can auto-verify or feed severity floors. |
| R8 | P1 | Add service discovery scan plan, fan-out cap, and per-service checkpoint/resume. | Adapt | M | Medium | Monorepo scan above cap stops before mass output; interrupted scan resumes by service/skill. |
| R9 | P1 | Add hash-pinned dependency locks and offline wheel bundle workflow. | Adapt | M | Low | CI can install with hashes; offline bundle can install engine and runtime deps without network. |
| R10 | P2 | Add Grafana and ThousandEyes render paths with sentinels and parse tests. | Adapt | M | Medium | Outputs are parseable, contain `REPLACE_ME__` for org-specific fields, and never claim live verification. |
| R11 | P2 | Add external-style generated repo second secret gate. | Lift/Adapt | S | Low | Independent scanner runs in generated repo CI, excluding known internal/vendor paths as needed. |
| R12 | P3 | Evaluate selected external schemas as examples only. | Defer | S | Low | No schema family split; useful field ideas are mapped into existing local kinds. |
| R13 | Never | Replace `sre-design` engine with `latent-sre` engine wholesale. | Reject | L | High | Rejected because it weakens byte-grounded authority and creates duplicate schema/CLI ownership. |

## Tier-B skill candidate matrix

| Candidate | Use as Tier-B? | Helps with | Does not help with | Integration target |
|---|---:|---|---|---|
| `assess-tech-stack` | Yes | Recall for runtimes, frameworks, build tools missed by deterministic collectors. | Authoritative version detection without lock/build evidence. | `TechStack` proposals and collector-gap findings. |
| `assess-criticality-and-data` | Already partially present | Business tier and data sensitivity prompts. | Deterministic severity floor unless tier is independently grounded. | Existing `Criticality` flow, `source_tier=llm`, `needs-review`. |
| `map-architecture` | Yes | C4-ish component/layer hints, architectural patterns for reviewer context. | Verified design patterns without code/config evidence. | `Architecture` proposals. |
| `map-infrastructure` | Yes | Platform ownership, VM/PCF/infrastructure context outside obvious manifests. | Live infrastructure truth. | `Deployment`, `Topology`, `NetworkTopology` proposals. |
| `map-pcf-application` | Selective | PCF routes, services, health checks, buildpack gaps. | Values/secrets from manifests. | Deterministic PCF collector first; Tier-B for missing/ambiguous fields. |
| `map-dependencies` | Yes | Critical dependency classification and hidden service coupling. | Verified dependency graph if no cited code/config. | `Dependency`, `BlastRadius`, `Topology` proposals. |
| `map-api-contracts` | Yes, high value | Missing OpenAPI/proto/schema files, undocumented endpoints, versioning gaps. | Contract correctness or payload semantics. | `Interface` proposals and `ResiliencyGap` for undocumented public APIs. |
| `map-messaging` | Yes, high value | Topics/queues, DLQ, redelivery, ordering, idempotency hints. | Dynamic topic names or broker runtime state. | `Interface`, `Dependency`, `Flow`, `ResiliencyGap`. |
| `map-jobs` | Yes | Undocumented jobs, idempotency/dedupe prompts, schedule risk. | Verified cron semantics without parser support. | `ScheduledJob` and gap proposals. |
| `map-delivery` | Yes | CI/CD and promotion evidence discovery. | Deployment success/failure rates. | `DeliveryPipeline` proposals. |
| `assess-logging` | Yes | Structured logging, correlation ID, sensitive log risk. | Runtime log coverage. | `Observability` and `SecurityPosture` proposals. |
| `assess-observability-coverage` | Yes, high value | Missing traces/metrics/synthetics and incident-debuggability gaps. | Live telemetry validation. | `Observability`, `Dashboard`, `ReadinessScore` advisories. |
| `assess-resiliency` | Already partially present | Recall for timeouts, retries, fallback, idempotency, swallowed failures. | Auto-verifying absence or severity. | Existing Tier-B gap flow plus deterministic promotion candidates. |
| `generate-slos` | Yes | Drafting SLO candidates from endpoints/critical flows. | Authoritative targets. | `SloSli` `needs-review` proposals only. |
| `generate-alerts` | Yes, constrained | Missing alert intent coverage and symptom/cause classification. | Tool-specific query generation or live alert validation. | `Alert` proposals; engine renders expressions. |
| `generate-dashboards` | Yes | Golden-signal dashboard coverage and missing panels. | Vendor JSON correctness without engine render. | `Dashboard` proposals; engine renders. |
| `generate-runbooks` | Yes | Reviewer-friendly runbook gaps and diagnosis/remediation drafts. | Safe remediation commands unless linted and reviewed. | `Runbook` proposals plus safety lint. |
| `publish-sre-repo` | No as scan skill | Useful as CI/publish checklist. | Anything agentic in target scan context. | Deterministic publish-role docs and CI only. |

## LLM-enhanced findings strategy

Use LLMs to raise questions the deterministic engine might miss:

- Recall gaps: "I see an endpoint without an SLO", "this producer has no DLQ evidence", "this job has no idempotency cue", "this dependency appears critical but lacks timeout evidence".
- Contradictions: Tier-A says a control exists but Tier-B cites a path suggesting it is bypassed; Tier-B claims absence but Tier-A has a rule firing elsewhere.
- Reviewer guidance: summarize why a gap matters, what evidence was cited, what an SRE should check next, and what deterministic signal would graduate the category.
- Coverage prioritization: rank observability, SLO, dashboard, and runbook gaps by incident debugging impact and service criticality.

Controls that must remain non-negotiable:

- Every Tier-B item has `source_tier=llm`, status `needs-review`, cited anchors, and a maximum candidate/noise budget.
- Tier-B output never raises severity floors, verifies an artifact, fills sentinels, emits live-tool queries, or publishes.
- Tier-B proposals must be re-grounded at cited bytes where possible and refuted/downgraded when deterministic signatures disagree.
- Repeated human-confirmed Tier-B categories become deterministic signatures, collectors, and tests.

## Concrete follow-up plan

1. Publish hardening first.

   Add local tests equivalent to external `test_assemble.py`: human edit preservation, `.proposed/` routing, duplicate output collision, malformed human edit preservation, orphan pruning, CODEOWNERS preservation, vendored schema validation, and hostile render target handling. Then implement manifest-backed assembly under `src/sre_kb/publish`.

2. Secret gate upgrade.

   Port the stronger scanner shape: known patterns, high-entropy opaque tokens, secret-ish key/value detection, UTF-16/latin-1 text handling, allowlist, and redacted findings. Change publish to block on findings before accepting the tree. Keep redaction as an explicit preview/sanitization mode, not the default way to make publish green.

3. Generated repo hardening.

   Add templates for generated repo validation workflow, CODEOWNERS sentinel, PR template, `.sre/version`, and vendored schemas. Ensure publish-stage tests assert all files exist and fail if sentinel/validation wiring is missing.

4. Role split.

   Add a target-scan Copilot agent/instructions profile that is read-only and no-terminal. Keep the current command-running agent only for maintaining `sre-design` itself.

5. Tier-B skill expansion.

   Add a local pipeline manifest and skill lint. Start with five skills: `map-api-contracts`, `map-messaging`, `assess-observability-coverage`, `generate-slos`, and `generate-dashboards`. Each should emit bounded proposals/worklists mapped to existing local kinds and unable to auto-verify.

6. Service fan-out and resumability.

   Add deterministic service discovery, fan-out cap by service count, and per-service/skill checkpoint state before scaling the skill suite across monorepos.

7. Supply-chain and offline readiness.

   Add hash-pinned requirements export and an offline bundle script after publish hardening lands, so enterprise/PCF runners can reproduce the engine without live dependency resolution.

## Bottom line

The winning path is not to choose one repo over the other. `sre-design` should keep the authority spine; `resiliency-skills` should donate operational hardening and the skill taxonomy. The most valuable immediate work is publish hardening, generated repo defenses, and explicit role separation. The Tier-B skill expansion is worth doing, but only after the output path is hard enough that more model-generated proposals do not increase operational risk.
