# Dependency snapshot

Evidence scope: resolver-backed production source edges only for coupling and cycle metrics.
`Ca` is distinct incoming neighbors, `Ce` is distinct outgoing neighbors, and
`I = Ce / (Ca + Ce)`. No health or severity grade is inferred.

## Coupling

| Node | Granularity | Ca | Ce | I |
|---|---|---:|---:|---:|
| `src/sre_kb/collectors/base.py` | module | 52 | 3 | 0.055 |
| `src/sre_kb/models/facts.py` | module | 42 | 1 | 0.023 |
| `src/sre_kb/util.py` | module | 37 | 0 | 0.000 |
| `src/sre_kb/config.py` | module | 14 | 0 | 0.000 |
| `src/sre_kb/tiers.py` | module | 13 | 0 | 0.000 |
| `group:sre-kb:sre_kb.config` | group | 11 | 0 | 0.000 |
| `src/sre_kb/workspace/__init__.py` | module | 10 | 1 | 0.091 |
| `group:sre-kb:sre_kb.collectors` | group | 9 | 8 | 0.471 |
| `src/sre_kb/collectors/llm/gap_finder.py` | module | 9 | 6 | 0.400 |
| `src/sre_kb/atlas/model.py` | module | 8 | 0 | 0.000 |
| `src/sre_kb/signatures.py` | module | 8 | 0 | 0.000 |
| `src/sre_kb/synth/emit.py` | module | 7 | 3 | 0.300 |
| `group:sre-kb:sre_kb.tiers` | group | 7 | 0 | 0.000 |
| `src/sre_kb/collectors/__init__.py` | module | 6 | 29 | 0.829 |
| `group:sre-kb:sre_kb.render` | group | 6 | 7 | 0.538 |
| `src/sre_kb/validation/structural.py` | module | 6 | 1 | 0.143 |
| `group:sre-kb:sre_kb.util` | group | 6 | 0 | 0.000 |
| `group:sre-kb:sre_kb.workspace` | group | 6 | 0 | 0.000 |
| `src/sre_kb/atlas/config.py` | module | 6 | 0 | 0.000 |
| `src/sre_kb/scoring/confidence.py` | module | 6 | 0 | 0.000 |
| `src/sre_kb/pipeline/confirm.py` | module | 5 | 12 | 0.706 |
| `src/sre_kb/render/project.py` | module | 5 | 7 | 0.583 |
| `src/sre_kb/atlas/evidence.py` | module | 5 | 3 | 0.375 |
| `src/sre_kb/collectors/common/openapi.py` | module | 5 | 3 | 0.375 |
| `src/sre_kb/reporting/__init__.py` | module | 5 | 3 | 0.375 |
| `src/sre_kb/atlas/graph.py` | module | 5 | 1 | 0.167 |
| `group:sre-kb:sre_kb.models` | group | 5 | 0 | 0.000 |
| `src/sre_kb/models/envelope.py` | module | 5 | 0 | 0.000 |
| `src/sre_kb/render/templating.py` | module | 5 | 0 | 0.000 |
| `group:sre-kb:sre_kb.pipeline` | group | 4 | 16 | 0.800 |
| `src/sre_kb/synth/scaffold.py` | module | 4 | 13 | 0.765 |
| `src/sre_kb/pipeline/gap_finder.py` | module | 4 | 11 | 0.733 |
| `group:sre-kb:sre_kb.validation` | group | 4 | 4 | 0.500 |
| `src/sre_kb/atlas/manifests.py` | module | 4 | 4 | 0.500 |
| `src/sre_kb/pipeline/contract.py` | module | 4 | 4 | 0.500 |
| `src/sre_kb/pipeline/diagram_narration.py` | module | 4 | 2 | 0.333 |
| `src/sre_kb/render/diagrams.py` | module | 4 | 2 | 0.333 |
| `src/sre_kb/synth/gap_prompt.py` | module | 4 | 2 | 0.333 |
| `group:sre-kb:sre_kb.registry` | group | 4 | 1 | 0.200 |
| `src/sre_kb/graduation/__init__.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/registry.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/render/__init__.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/validation/provenance.py` | module | 4 | 1 | 0.200 |
| `group:sre-kb:sre_kb.inventory_signatures` | group | 4 | 0 | 0.000 |
| `group:sre-kb:sre_kb.signatures` | group | 4 | 0 | 0.000 |
| `src/sre_kb/inventory_signatures.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/parsing/code_model.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/reporting/narrative.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/validation/gating.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/pipeline/worklist_run.py` | module | 3 | 20 | 0.870 |
| `group:sre-kb:sre_kb.synth` | group | 3 | 12 | 0.800 |
| `src/sre_kb/pipeline/alerts_draft.py` | module | 3 | 9 | 0.750 |
| `src/sre_kb/pipeline/architecture.py` | module | 3 | 8 | 0.727 |
| `src/sre_kb/pipeline/runbooks_draft.py` | module | 3 | 7 | 0.700 |
| `group:sre-kb:sre_kb.reporting` | group | 3 | 5 | 0.625 |
| `src/sre_kb/pipeline/pcf_review.py` | module | 3 | 3 | 0.500 |
| `src/sre_kb/pipeline/areas.py` | module | 3 | 2 | 0.400 |
| `src/sre_kb/render/plain.py` | module | 3 | 2 | 0.400 |
| `group:sre-kb:sre_kb.graduation` | group | 3 | 1 | 0.250 |
| `src/sre_kb/pipeline/__init__.py` | module | 3 | 1 | 0.250 |
| `src/sre_kb/render/alerts.py` | module | 3 | 1 | 0.250 |
| `src/sre_kb/validation/challenge.py` | module | 3 | 1 | 0.250 |
| `group:sre-kb:sre_kb` | group | 3 | 0 | 0.000 |
| `group:sre-kb:sre_kb.parsing` | group | 3 | 0 | 0.000 |
| `src/sre_kb/__init__.py` | module | 3 | 0 | 0.000 |
| `src/sre_kb/parsing/structural.py` | module | 3 | 0 | 0.000 |
| `src/sre_kb/pipeline/orchestrator.py` | module | 2 | 34 | 0.944 |
| `group:sre-kb:sre_kb.publish` | group | 2 | 8 | 0.800 |
| `src/sre_kb/synth/draft_prompts.py` | module | 2 | 6 | 0.750 |
| `src/sre_kb/collectors/common/idempotency.py` | module | 2 | 4 | 0.667 |
| `src/sre_kb/collectors/java_spring/messaging.py` | module | 2 | 4 | 0.667 |
| `src/sre_kb/collectors/common/manifest_pcf.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/collectors/java_spring/flow_builder.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/estate/topology.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/publish/forge/__init__.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/render/depmap.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/reporting/findings.py` | module | 2 | 3 | 0.600 |
| `group:sre-kb:sre_kb.scoring` | group | 2 | 2 | 0.500 |
| `src/sre_kb/parsing/operational.py` | module | 2 | 2 | 0.500 |
| `src/sre_kb/pipeline/challenge_apply.py` | module | 2 | 2 | 0.500 |
| `src/sre_kb/pipeline/challenge_run.py` | module | 2 | 2 | 0.500 |
| `src/sre_kb/scoring/readiness.py` | module | 2 | 2 | 0.500 |
| `group:sre-kb:sre_kb.taxonomy` | group | 2 | 1 | 0.333 |
| `src/sre_kb/publish/__init__.py` | module | 2 | 1 | 0.333 |
| `src/sre_kb/security/__init__.py` | module | 2 | 1 | 0.333 |
| `src/sre_kb/taxonomy.py` | module | 2 | 1 | 0.333 |
| `group:sre-kb:sre_kb.clone` | group | 2 | 0 | 0.000 |
| `group:sre-kb:sre_kb.llm` | group | 2 | 0 | 0.000 |
| `group:sre-kb:sre_kb.security` | group | 2 | 0 | 0.000 |
| `src/sre_kb/clone.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/llm/provider.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/publish/forge/base.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/validation/report.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/pipeline/autopilot.py` | module | 1 | 16 | 0.941 |
| `src/sre_kb/estate/runner.py` | module | 1 | 14 | 0.933 |
| `group:sre-kb:sre_kb.estate` | group | 1 | 10 | 0.909 |
| `src/sre_kb/atlas/source.py` | module | 1 | 9 | 0.900 |
| `src/sre_kb/publish/pr_builder.py` | module | 1 | 9 | 0.900 |
| `src/sre_kb/synth/inventory.py` | module | 1 | 9 | 0.900 |
| `src/sre_kb/atlas/runner.py` | module | 1 | 8 | 0.889 |
| `src/sre_kb/atlas/calls.py` | module | 1 | 5 | 0.833 |
| `src/sre_kb/atlas/overlays.py` | module | 1 | 5 | 0.833 |
| `src/sre_kb/pipeline/graduation_draft.py` | module | 1 | 5 | 0.833 |
| `src/sre_kb/collectors/dotnet_steeltoe/resiliency.py` | module | 1 | 4 | 0.800 |
| `src/sre_kb/collectors/java_spring/annotations.py` | module | 1 | 4 | 0.800 |
| `src/sre_kb/collectors/java_spring/resiliency.py` | module | 1 | 4 | 0.800 |
| `src/sre_kb/render/copilot.py` | module | 1 | 4 | 0.800 |
| `group:sre-kb:sre_kb.flow` | group | 1 | 3 | 0.750 |
| `group:sre-kb:sre_kb.scan_plan` | group | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/common/cf_env.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/common/criticality.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/common/feature_flags.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/common/slo_catalog.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/dotnet_steeltoe/annotations.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/dotnet_steeltoe/build.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/dotnet_steeltoe/config.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/go_net/endpoints.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/go_net/go_mod.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/java_spring/build.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/java_spring/config_props.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/java_spring/jobs.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/java_spring/resiliency_params.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/node_express/endpoints.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/node_express/frontend.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/node_express/package_json.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/collectors/python_fastapi/endpoints.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/flow/budget_check.py` | module | 1 | 3 | 0.750 |
| `src/sre_kb/scan_plan.py` | module | 1 | 3 | 0.750 |
| `group:sre-kb:sre_kb.atlas` | group | 1 | 2 | 0.667 |
| `group:sre-kb:sre_kb.eval` | group | 1 | 2 | 0.667 |
| `src/sre_kb/collectors/common/delivery_pipeline.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/collectors/java_spring/log_statements.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/collectors/java_spring/observability.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/estate/__init__.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/eval/scorecard.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/publish/forge/github.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/validation/copilot_gap.py` | module | 1 | 2 | 0.667 |
| `src/sre_kb/atlas/__init__.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/atlas/render.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/drift/__init__.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/graduation/state.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/parsing/__init__.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/render/dashboards.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/reporting/coverage.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/reporting/human_report.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/synth/context_pack.py` | module | 1 | 1 | 0.500 |
| `src/sre_kb/validation/__init__.py` | module | 1 | 1 | 0.500 |
| `group:sre-kb:sre_kb.drift` | group | 1 | 0 | 0.000 |
| `src/sre_kb/drift/diff.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/publish/forge/local.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/publish/manifest.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/render/catalog.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/scoring/risk.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/security/secret_scan.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/synth/worklist.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/validation/crossref.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/validation/safety.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/validation/substance.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/workspace/layout.py` | module | 1 | 0 | 0.000 |
| `src/sre_kb/cli.py` | module | 0 | 38 | 1.000 |
| `group:sre-kb:sre_kb.cli` | group | 0 | 18 | 1.000 |
| `src/sre_kb/synth/__init__.py` | module | 0 | 1 | 1.000 |

## Strongly connected components

1. **group** — `group:sre-kb:sre_kb.collectors` → `group:sre-kb:sre_kb.flow`
2. **group** — `group:sre-kb:sre_kb.pipeline` → `group:sre-kb:sre_kb.publish` → `group:sre-kb:sre_kb.render` → `group:sre-kb:sre_kb.reporting` → `group:sre-kb:sre_kb.synth` → `group:sre-kb:sre_kb.validation`

## Cross-package import matrix

Row depends on column. Cell values are resolver-backed production import counts, not API calls
and not a health grade. The matrix shows 14 of 30 packages (SCC members first, then highest import traffic); 16 lower-traffic package(s) remain in the incoming/outgoing list.

| | `sre_kb.pipeline` | `sre_kb.collectors` | `sre_kb.synth` | `sre_kb.render` | `sre_kb.validation` | `sre_kb.reporting` | `sre_kb.publish` | `sre_kb.flow` | `sre_kb.cli` | `sre_kb.models` | `sre_kb.util` | `sre_kb.workspace` | `sre_kb.estate` | `sre_kb.config` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `sre_kb.pipeline` | - | 36 | 19 | 11 | 16 | 8 | 1 | 0 | 0 | 7 | 6 | 5 | 0 | 4 |
| `sre_kb.collectors` | 0 | - | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 33 | 24 | 0 | 0 | 0 |
| `sre_kb.synth` | 0 | 7 | - | 3 | 0 | 0 | 0 | 0 | 0 | 5 | 3 | 0 | 0 | 1 |
| `sre_kb.render` | 0 | 1 | 0 | - | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 0 | 0 |
| `sre_kb.validation` | 1 | 2 | 0 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `sre_kb.reporting` | 0 | 0 | 0 | 1 | 0 | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `sre_kb.publish` | 0 | 0 | 0 | 1 | 0 | 1 | - | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| `sre_kb.flow` | 0 | 1 | 0 | 0 | 0 | 0 | 0 | - | 0 | 1 | 1 | 0 | 0 | 0 |
| `sre_kb.cli` | 22 | 5 | 1 | 10 | 2 | 3 | 2 | 0 | - | 0 | 0 | 15 | 1 | 2 |
| `sre_kb.models` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 | 0 |
| `sre_kb.util` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | 0 |
| `sre_kb.workspace` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 |
| `sre_kb.estate` | 0 | 2 | 1 | 2 | 4 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | - | 1 |
| `sre_kb.config` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |

## Highest-traffic cross-package imports

| From | To | Import count |
|---|---|---:|
| `sre_kb.pipeline` | `sre_kb.collectors` | 36 |
| `sre_kb.collectors` | `sre_kb.models` | 33 |
| `sre_kb.collectors` | `sre_kb.util` | 24 |
| `sre_kb.cli` | `sre_kb.pipeline` | 22 |
| `sre_kb.pipeline` | `sre_kb.synth` | 19 |
| `sre_kb.pipeline` | `sre_kb.validation` | 16 |
| `sre_kb.cli` | `sre_kb.workspace` | 15 |
| `sre_kb.pipeline` | `sre_kb.render` | 11 |
| `sre_kb.cli` | `sre_kb.render` | 10 |
| `sre_kb.pipeline` | `sre_kb.reporting` | 8 |
| `sre_kb.synth` | `sre_kb.collectors` | 7 |
| `sre_kb.pipeline` | `sre_kb.models` | 7 |
| `sre_kb.pipeline` | `sre_kb.tiers` | 6 |
| `sre_kb.pipeline` | `sre_kb.util` | 6 |
| `sre_kb.cli` | `sre_kb.graduation` | 6 |

Counts are edge weights. They do not assign severity or a refactoring mandate.

## Incoming and outgoing by package

- `sre_kb` — outgoing: _none_; incoming: `sre_kb.cli` (1), `sre_kb.publish` (1), `sre_kb.synth` (1)
- `sre_kb.atlas` — outgoing: `sre_kb.parsing` (4), `sre_kb.collectors` (1); incoming: `sre_kb.cli` (4)
- `sre_kb.cli` — outgoing: `sre_kb.pipeline` (22), `sre_kb.workspace` (15), `sre_kb.render` (10), `sre_kb.graduation` (6), `sre_kb.collectors` (5), `sre_kb.llm` (5), `sre_kb.atlas` (4), `sre_kb.reporting` (3), `sre_kb.config` (2), `sre_kb.publish` (2), `sre_kb.scan_plan` (2), `sre_kb.security` (2), `sre_kb.validation` (2), `sre_kb` (1), `sre_kb.drift` (1), `sre_kb.estate` (1), `sre_kb.eval` (1), `sre_kb.synth` (1); incoming: _none_
- `sre_kb.clone` — outgoing: _none_; incoming: `sre_kb.estate` (1), `sre_kb.pipeline` (1)
- `sre_kb.collectors` — outgoing: `sre_kb.models` (33), `sre_kb.util` (24), `sre_kb.signatures` (5), `sre_kb.parsing` (2), `sre_kb.tiers` (2), `sre_kb.flow` (1), `sre_kb.inventory_signatures` (1), `sre_kb.taxonomy` (1); incoming: `sre_kb.pipeline` (36), `sre_kb.synth` (7), `sre_kb.cli` (5), `sre_kb.estate` (2), `sre_kb.validation` (2), `sre_kb.atlas` (1), `sre_kb.flow` (1), `sre_kb.render` (1), `sre_kb.scan_plan` (1)
- `sre_kb.config` — outgoing: _none_; incoming: `sre_kb.pipeline` (4), `sre_kb.cli` (2), `sre_kb.estate` (1), `sre_kb.graduation` (1), `sre_kb.publish` (1), `sre_kb.registry` (1), `sre_kb.reporting` (1), `sre_kb.scan_plan` (1), `sre_kb.synth` (1), `sre_kb.taxonomy` (1), `sre_kb.validation` (1)
- `sre_kb.drift` — outgoing: _none_; incoming: `sre_kb.cli` (1)
- `sre_kb.estate` — outgoing: `sre_kb.validation` (4), `sre_kb.collectors` (2), `sre_kb.render` (2), `sre_kb.util` (2), `sre_kb.clone` (1), `sre_kb.config` (1), `sre_kb.inventory_signatures` (1), `sre_kb.synth` (1), `sre_kb.tiers` (1), `sre_kb.workspace` (1); incoming: `sre_kb.cli` (1)
- `sre_kb.eval` — outgoing: `sre_kb.pipeline` (1), `sre_kb.workspace` (1); incoming: `sre_kb.cli` (1)
- `sre_kb.flow` — outgoing: `sre_kb.collectors` (1), `sre_kb.models` (1), `sre_kb.util` (1); incoming: `sre_kb.collectors` (1)
- `sre_kb.graduation` — outgoing: `sre_kb.config` (1); incoming: `sre_kb.cli` (6), `sre_kb.pipeline` (2), `sre_kb.reporting` (2)
- `sre_kb.inventory_signatures` — outgoing: _none_; incoming: `sre_kb.collectors` (1), `sre_kb.estate` (1), `sre_kb.scoring` (1), `sre_kb.synth` (1)
- `sre_kb.llm` — outgoing: _none_; incoming: `sre_kb.cli` (5), `sre_kb.pipeline` (1)
- `sre_kb.models` — outgoing: _none_; incoming: `sre_kb.collectors` (33), `sre_kb.pipeline` (7), `sre_kb.synth` (5), `sre_kb.flow` (1), `sre_kb.scoring` (1)
- `sre_kb.parsing` — outgoing: _none_; incoming: `sre_kb.atlas` (4), `sre_kb.collectors` (2), `sre_kb.synth` (2)
- `sre_kb.pipeline` — outgoing: `sre_kb.collectors` (36), `sre_kb.synth` (19), `sre_kb.validation` (16), `sre_kb.render` (11), `sre_kb.reporting` (8), `sre_kb.models` (7), `sre_kb.tiers` (6), `sre_kb.util` (6), `sre_kb.scoring` (5), `sre_kb.workspace` (5), `sre_kb.config` (4), `sre_kb.graduation` (2), `sre_kb.clone` (1), `sre_kb.llm` (1), `sre_kb.publish` (1), `sre_kb.signatures` (1); incoming: `sre_kb.cli` (22), `sre_kb.eval` (1), `sre_kb.scan_plan` (1), `sre_kb.validation` (1)
- `sre_kb.publish` — outgoing: `sre_kb` (1), `sre_kb.config` (1), `sre_kb.registry` (1), `sre_kb.render` (1), `sre_kb.reporting` (1), `sre_kb.security` (1), `sre_kb.tiers` (1), `sre_kb.workspace` (1); incoming: `sre_kb.cli` (2), `sre_kb.pipeline` (1)
- `sre_kb.registry` — outgoing: `sre_kb.config` (1); incoming: `sre_kb.publish` (1), `sre_kb.render` (1), `sre_kb.reporting` (1), `sre_kb.synth` (1)
- `sre_kb.render` — outgoing: `sre_kb.util` (2), `sre_kb.collectors` (1), `sre_kb.registry` (1), `sre_kb.taxonomy` (1), `sre_kb.tiers` (1), `sre_kb.validation` (1), `sre_kb.workspace` (1); incoming: `sre_kb.pipeline` (11), `sre_kb.cli` (10), `sre_kb.synth` (3), `sre_kb.estate` (2), `sre_kb.publish` (1), `sre_kb.reporting` (1)
- `sre_kb.reporting` — outgoing: `sre_kb.graduation` (2), `sre_kb.config` (1), `sre_kb.registry` (1), `sre_kb.render` (1), `sre_kb.tiers` (1); incoming: `sre_kb.pipeline` (8), `sre_kb.cli` (3), `sre_kb.publish` (1)
- `sre_kb.scan_plan` — outgoing: `sre_kb.collectors` (1), `sre_kb.config` (1), `sre_kb.pipeline` (1); incoming: `sre_kb.cli` (2)
- `sre_kb.scoring` — outgoing: `sre_kb.inventory_signatures` (1), `sre_kb.models` (1); incoming: `sre_kb.pipeline` (5), `sre_kb.synth` (4)
- `sre_kb.security` — outgoing: _none_; incoming: `sre_kb.cli` (2), `sre_kb.publish` (1)
- `sre_kb.signatures` — outgoing: _none_; incoming: `sre_kb.collectors` (5), `sre_kb.pipeline` (1), `sre_kb.synth` (1), `sre_kb.validation` (1)
- `sre_kb.synth` — outgoing: `sre_kb.collectors` (7), `sre_kb.models` (5), `sre_kb.scoring` (4), `sre_kb.render` (3), `sre_kb.util` (3), `sre_kb.parsing` (2), `sre_kb` (1), `sre_kb.config` (1), `sre_kb.inventory_signatures` (1), `sre_kb.registry` (1), `sre_kb.signatures` (1), `sre_kb.tiers` (1); incoming: `sre_kb.pipeline` (19), `sre_kb.cli` (1), `sre_kb.estate` (1)
- `sre_kb.taxonomy` — outgoing: `sre_kb.config` (1); incoming: `sre_kb.collectors` (1), `sre_kb.render` (1)
- `sre_kb.tiers` — outgoing: _none_; incoming: `sre_kb.pipeline` (6), `sre_kb.collectors` (2), `sre_kb.estate` (1), `sre_kb.publish` (1), `sre_kb.render` (1), `sre_kb.reporting` (1), `sre_kb.synth` (1)
- `sre_kb.util` — outgoing: _none_; incoming: `sre_kb.collectors` (24), `sre_kb.pipeline` (6), `sre_kb.synth` (3), `sre_kb.estate` (2), `sre_kb.render` (2), `sre_kb.flow` (1)
- `sre_kb.validation` — outgoing: `sre_kb.collectors` (2), `sre_kb.config` (1), `sre_kb.pipeline` (1), `sre_kb.signatures` (1); incoming: `sre_kb.pipeline` (16), `sre_kb.estate` (4), `sre_kb.cli` (2), `sre_kb.render` (1)
- `sre_kb.workspace` — outgoing: _none_; incoming: `sre_kb.cli` (15), `sre_kb.pipeline` (5), `sre_kb.estate` (1), `sre_kb.eval` (1), `sre_kb.publish` (1), `sre_kb.render` (1)

## Cycle-closing imports

1. `sre_kb.collectors` → `sre_kb.flow`
  - `sre_kb.collectors` → `sre_kb.flow`: `src/sre_kb/collectors/__init__.py:36`
  - `sre_kb.flow` → `sre_kb.collectors`: `src/sre_kb/flow/budget_check.py:6`
2. `sre_kb.pipeline` → `sre_kb.publish` → `sre_kb.render` → `sre_kb.reporting` → `sre_kb.synth` → `sre_kb.validation`
  - `sre_kb.pipeline` → `sre_kb.publish`: `src/sre_kb/pipeline/orchestrator.py:326`
  - `sre_kb.pipeline` → `sre_kb.render`: `src/sre_kb/pipeline/autopilot.py:131`, `src/sre_kb/pipeline/autopilot.py:90`, `src/sre_kb/pipeline/alerts_draft.py:31`, `src/sre_kb/pipeline/worklist_run.py:216`, `src/sre_kb/pipeline/worklist_run.py:160`, `src/sre_kb/pipeline/worklist_run.py:178`, `src/sre_kb/pipeline/worklist_run.py:215`, `src/sre_kb/pipeline/worklist_run.py:256`, `src/sre_kb/pipeline/diagram_narration.py:20`, `src/sre_kb/pipeline/orchestrator.py:321`, `src/sre_kb/pipeline/autopilot.py:91`
  - `sre_kb.pipeline` → `sre_kb.reporting`: `src/sre_kb/pipeline/worklist_run.py:218`, `src/sre_kb/pipeline/orchestrator.py:288`, `src/sre_kb/pipeline/orchestrator.py:26`, `src/sre_kb/pipeline/autopilot.py:92`, `src/sre_kb/pipeline/worklist_run.py:217`, `src/sre_kb/pipeline/runbooks_draft.py:28`, `src/sre_kb/pipeline/autopilot.py:93`, `src/sre_kb/pipeline/orchestrator.py:286`
  - `sre_kb.pipeline` → `sre_kb.synth`: `src/sre_kb/pipeline/orchestrator.py:28`, `src/sre_kb/pipeline/runbooks_draft.py:31`, `src/sre_kb/pipeline/architecture.py:30`, `src/sre_kb/pipeline/orchestrator.py:287`, `src/sre_kb/pipeline/alerts_draft.py:33`, `src/sre_kb/pipeline/graduation_draft.py:23`, `src/sre_kb/pipeline/runbooks_draft.py:30`, `src/sre_kb/pipeline/architecture.py:29`, `src/sre_kb/pipeline/worklist_run.py:143`, `src/sre_kb/pipeline/worklist_run.py:161`, `src/sre_kb/pipeline/worklist_run.py:179`, `src/sre_kb/pipeline/worklist_run.py:200` (+7 more)
  - `sre_kb.pipeline` → `sre_kb.validation`: `src/sre_kb/pipeline/orchestrator.py:43`, `src/sre_kb/pipeline/orchestrator.py:44`, `src/sre_kb/pipeline/orchestrator.py:32`, `src/sre_kb/pipeline/challenge_apply.py:10`, `src/sre_kb/pipeline/orchestrator.py:42`, `src/sre_kb/pipeline/confirm.py:332`, `src/sre_kb/pipeline/orchestrator.py:40`, `src/sre_kb/pipeline/gap_finder.py:27`, `src/sre_kb/pipeline/orchestrator.py:41`, `src/sre_kb/pipeline/confirm.py:331`, `src/sre_kb/pipeline/gap_finder.py:26`, `src/sre_kb/pipeline/orchestrator.py:39` (+4 more)
  - `sre_kb.publish` → `sre_kb.render`: `src/sre_kb/publish/pr_builder.py:14`
  - `sre_kb.publish` → `sre_kb.reporting`: `src/sre_kb/publish/pr_builder.py:262`
  - `sre_kb.render` → `sre_kb.validation`: `src/sre_kb/render/project.py:31`
  - `sre_kb.reporting` → `sre_kb.render`: `src/sre_kb/reporting/human_report.py:8`
  - `sre_kb.synth` → `sre_kb.render`: `src/sre_kb/synth/scaffold.py:19`, `src/sre_kb/synth/scaffold.py:578`, `src/sre_kb/synth/scaffold.py:8`
  - `sre_kb.validation` → `sre_kb.pipeline`: `src/sre_kb/validation/copilot_gap.py:16`


## Resolver blind spots

| Unknown code | Count |
|---|---:|
| `overlay.codeowners-missing` | 1 |
| `resolver.python-dynamic-import` | 1 |
