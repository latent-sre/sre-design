# Artifact envelope (every kind shares this)

```yaml
apiVersion: sre.kb/v1alpha1
kind: <Kind>
metadata: { name, service, owner?, domain? }   # name: ^[a-z0-9][a-z0-9-]*$
spec: { ...kind-specific... }
evidence:                                       # >=1 required for status=verified
  - { repo, commit, path, lines: {start,end}, excerptHash: "sha256:<64hex>", detector }
confidence: 0.0-1.0
status: verified | needs-review | rejected
provenanceMode: deterministic | llm-asserted
crossRefs: [ { kind, name, relation } ]         # implements|depends-on|emits|alerts-on|mitigates|covers
generatedBy: { tool, driver: engine|copilot, promptVersion?, generatedAt? }
```

- Validate with `sre-kb validate-kb <dir>` or `--to-stage validate`.
- `verified` requires `confidence >= 0.7` **and** at least one provenance-verified
  evidence item; otherwise the artifact lands in `needs-review` (never dropped).
