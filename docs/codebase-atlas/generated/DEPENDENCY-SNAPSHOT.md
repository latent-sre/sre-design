# Dependency snapshot

Evidence scope: resolver-backed production source edges only for coupling and cycle metrics.
`Ca` is distinct incoming neighbors, `Ce` is distinct outgoing neighbors, and
`I = Ce / (Ca + Ce)`. No health or severity grade is inferred.

## Coupling

| Node | Granularity | Ca | Ce | I |
|---|---|---:|---:|---:|
| `src/sre_kb/collectors/base.py` | module | 51 | 3 | 0.056 |
| `src/sre_kb/models/facts.py` | module | 42 | 1 | 0.023 |
| `src/sre_kb/util.py` | module | 36 | 0 | 0.000 |
| `src/sre_kb/config.py` | module | 14 | 0 | 0.000 |
| `src/sre_kb/tiers.py` | module | 13 | 0 | 0.000 |
| `group:sre-kb:sre_kb.config` | group | 11 | 0 | 0.000 |
| `src/sre_kb/workspace/__init__.py` | module | 10 | 1 | 0.091 |
| `src/sre_kb/collectors/llm/gap_finder.py` | module | 9 | 6 | 0.400 |
| `group:sre-kb:sre_kb.collectors` | group | 8 | 8 | 0.500 |
| `src/sre_kb/signatures.py` | module | 8 | 0 | 0.000 |
| `src/sre_kb/synth/emit.py` | module | 7 | 3 | 0.300 |
| `group:sre-kb:sre_kb.tiers` | group | 7 | 0 | 0.000 |
| `src/sre_kb/atlas/model.py` | module | 7 | 0 | 0.000 |
| `src/sre_kb/collectors/__init__.py` | module | 6 | 29 | 0.829 |
| `src/sre_kb/validation/structural.py` | module | 6 | 1 | 0.143 |
| `group:sre-kb:sre_kb.util` | group | 6 | 0 | 0.000 |
| `group:sre-kb:sre_kb.workspace` | group | 6 | 0 | 0.000 |
| `src/sre_kb/atlas/config.py` | module | 6 | 0 | 0.000 |
| `src/sre_kb/scoring/confidence.py` | module | 6 | 0 | 0.000 |
| `src/sre_kb/pipeline/confirm.py` | module | 5 | 12 | 0.706 |
| `group:sre-kb:sre_kb.render` | group | 5 | 6 | 0.545 |
| `src/sre_kb/render/project.py` | module | 5 | 6 | 0.545 |
| `src/sre_kb/collectors/common/openapi.py` | module | 5 | 3 | 0.375 |
| `src/sre_kb/reporting/__init__.py` | module | 5 | 2 | 0.286 |
| `group:sre-kb:sre_kb.models` | group | 5 | 0 | 0.000 |
| `src/sre_kb/models/envelope.py` | module | 5 | 0 | 0.000 |
| `group:sre-kb:sre_kb.pipeline` | group | 4 | 16 | 0.800 |
| `src/sre_kb/synth/scaffold.py` | module | 4 | 12 | 0.750 |
| `src/sre_kb/pipeline/gap_finder.py` | module | 4 | 11 | 0.733 |
| `group:sre-kb:sre_kb.validation` | group | 4 | 4 | 0.500 |
| `src/sre_kb/pipeline/contract.py` | module | 4 | 4 | 0.500 |
| `src/sre_kb/atlas/evidence.py` | module | 4 | 3 | 0.429 |
| `src/sre_kb/pipeline/diagram_narration.py` | module | 4 | 2 | 0.333 |
| `src/sre_kb/render/diagrams.py` | module | 4 | 2 | 0.333 |
| `src/sre_kb/synth/gap_prompt.py` | module | 4 | 2 | 0.333 |
| `group:sre-kb:sre_kb.registry` | group | 4 | 1 | 0.200 |
| `src/sre_kb/atlas/graph.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/graduation/__init__.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/registry.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/render/__init__.py` | module | 4 | 1 | 0.200 |
| `src/sre_kb/validation/provenance.py` | module | 4 | 1 | 0.200 |
| `group:sre-kb:sre_kb.inventory_signatures` | group | 4 | 0 | 0.000 |
| `group:sre-kb:sre_kb.signatures` | group | 4 | 0 | 0.000 |
| `src/sre_kb/inventory_signatures.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/reporting/narrative.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/validation/gating.py` | module | 4 | 0 | 0.000 |
| `src/sre_kb/pipeline/worklist_run.py` | module | 3 | 20 | 0.870 |
| `group:sre-kb:sre_kb.synth` | group | 3 | 11 | 0.786 |
| `src/sre_kb/pipeline/alerts_draft.py` | module | 3 | 9 | 0.750 |
| `src/sre_kb/pipeline/architecture.py` | module | 3 | 8 | 0.727 |
| `src/sre_kb/pipeline/runbooks_draft.py` | module | 3 | 7 | 0.700 |
| `group:sre-kb:sre_kb.reporting` | group | 3 | 4 | 0.571 |
| `src/sre_kb/atlas/manifests.py` | module | 3 | 4 | 0.571 |
| `src/sre_kb/pipeline/pcf_review.py` | module | 3 | 3 | 0.500 |
| `src/sre_kb/pipeline/areas.py` | module | 3 | 2 | 0.400 |
| `group:sre-kb:sre_kb.graduation` | group | 3 | 1 | 0.250 |
| `src/sre_kb/pipeline/__init__.py` | module | 3 | 1 | 0.250 |
| `src/sre_kb/render/alerts.py` | module | 3 | 1 | 0.250 |
| `src/sre_kb/validation/challenge.py` | module | 3 | 1 | 0.250 |
| `group:sre-kb:sre_kb` | group | 3 | 0 | 0.000 |
| `src/sre_kb/__init__.py` | module | 3 | 0 | 0.000 |
| `src/sre_kb/pipeline/orchestrator.py` | module | 2 | 34 | 0.944 |
| `group:sre-kb:sre_kb.publish` | group | 2 | 8 | 0.800 |
| `src/sre_kb/collectors/common/idempotency.py` | module | 2 | 4 | 0.667 |
| `src/sre_kb/collectors/java_spring/messaging.py` | module | 2 | 4 | 0.667 |
| `src/sre_kb/synth/draft_prompts.py` | module | 2 | 4 | 0.667 |
| `src/sre_kb/collectors/common/manifest_pcf.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/collectors/java_spring/flow_builder.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/estate/topology.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/publish/forge/__init__.py` | module | 2 | 3 | 0.600 |
| `src/sre_kb/reporting/findings.py` | module | 2 | 3 | 0.600 |
| `group:sre-kb:sre_kb.scoring` | group | 2 | 2 | 0.500 |
| `src/sre_kb/pipeline/challenge_apply.py` | module | 2 | 2 | 0.500 |
| `src/sre_kb/pipeline/challenge_run.py` | module | 2 | 2 | 0.500 |
| `src/sre_kb/scoring/readiness.py` | module | 2 | 2 | 0.500 |
| `group:sre-kb:sre_kb.taxonomy` | group | 2 | 1 | 0.333 |
| `src/sre_kb/publish/__init__.py` | module | 2 | 1 | 0.333 |
| `src/sre_kb/security/__init__.py` | module | 2 | 1 | 0.333 |
| `src/sre_kb/taxonomy.py` | module | 2 | 1 | 0.333 |
| `group:sre-kb:sre_kb.clone` | group | 2 | 0 | 0.000 |
| `group:sre-kb:sre_kb.llm` | group | 2 | 0 | 0.000 |
| `group:sre-kb:sre_kb.parsing` | group | 2 | 0 | 0.000 |
| `group:sre-kb:sre_kb.security` | group | 2 | 0 | 0.000 |
| `src/sre_kb/clone.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/llm/provider.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/parsing/code_model.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/publish/forge/base.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/render/templating.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/validation/report.py` | module | 2 | 0 | 0.000 |
| `src/sre_kb/pipeline/autopilot.py` | module | 1 | 16 | 0.941 |
| `src/sre_kb/estate/runner.py` | module | 1 | 13 | 0.929 |
| `group:sre-kb:sre_kb.estate` | group | 1 | 10 | 0.909 |
| `src/sre_kb/publish/pr_builder.py` | module | 1 | 9 | 0.900 |
| `src/sre_kb/synth/inventory.py` | module | 1 | 9 | 0.900 |
| `src/sre_kb/atlas/runner.py` | module | 1 | 8 | 0.889 |
| `src/sre_kb/atlas/source.py` | module | 1 | 6 | 0.857 |
| `src/sre_kb/atlas/overlays.py` | module | 1 | 5 | 0.833 |
| `src/sre_kb/pipeline/graduation_draft.py` | module | 1 | 5 | 0.833 |
| `src/sre_kb/collectors/dotnet_steeltoe/resiliency.py` | module | 1 | 4 | 0.800 |
| `src/sre_kb/collectors/java_spring/annotations.py` | module | 1 | 4 | 0.800 |
| `src/sre_kb/collectors/java_spring/resiliency.py` | module | 1 | 4 | 0.800 |
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
| `src/sre_kb/render/copilot.py` | module | 1 | 3 | 0.750 |
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
2. **group** — `group:sre-kb:sre_kb.pipeline` → `group:sre-kb:sre_kb.publish` → `group:sre-kb:sre_kb.render` → `group:sre-kb:sre_kb.synth` → `group:sre-kb:sre_kb.validation`

## Resolver blind spots

| Unknown code | Count |
|---|---:|
| `overlay.codeowners-missing` | 1 |
| `resolver.python-dynamic-import` | 1 |
