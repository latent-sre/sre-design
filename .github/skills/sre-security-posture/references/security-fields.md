# SecurityPosture artifact — field guide

```yaml
kind: SecurityPosture
spec:
  controls: [secret-scan, tls, dependency-audit]   # discrete safeguards present (cited)
  authn: oauth2 | oidc | mtls | basic | none-found  # authentication mechanism
  authz: role-based | abac | method-level | none-found
  encryption: tls-in-transit | kms-at-rest | none-found
  secrets: externalized | vault | env | hardcoded-RISK
  openRisks:                                         # what a reviewer must still confirm/close
    - no at-rest encryption signal found — verify datastore config
```

**What grounds each field (cite one of these, or it's an open risk)**

| field | evidence that grounds it |
|------|---------------------------|
| `authn: oauth2/oidc` | a `spring-security-oauth2` / `passport` / `oidc` dependency or an `oauth`/`issuer-uri` config block |
| `authn: mtls` | a mutual-TLS / client-cert config |
| `authz: role-based` | `@PreAuthorize`/`hasRole`, a roles/authorities config |
| `authz: method-level` | method-security annotations enabled |
| `encryption: tls-in-transit` | `server.ssl.*` / `https`-only / ingress TLS config |
| `encryption: kms-at-rest` | a KMS / encrypted-volume / `encryption=true` datastore setting |
| `secrets: externalized/vault/env` | a Vault ref, `valueFrom: secretKeyRef`, or env-var secret reference |
| `secrets: hardcoded-RISK` | a literal credential in code/config — record location + type, **mask the value** |
| `controls: secret-scan` | a detect-secrets / gitleaks step in CI |

**What good looks like**

- Every populated control cites real evidence; unevidenced expectations live in `openRisks`.
- No secret value (or excerpt containing one) ever appears — only its location and type.
- `crossRefs` link to the `Criticality` artifact (data classification) and the `ReadinessScore`.
- `status: needs-review` — a security summary a human ratifies, never a severity input.
