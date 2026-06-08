---
name: sre-security-posture
description: >-
  Assess-phase (Tier-B) security-posture authorer — record a service's security controls (authn,
  authz, encryption, secret handling) and open risks as a needs-review SecurityPosture artifact,
  each grounded in cited security config or dependencies. Use when asked about a service's security
  posture, auth/encryption/secret handling, or to fill the security section of a production-readiness
  review. You propose controls from real evidence; the engine never raises severity off them, and
  data classification (PII/PCI) stays the engine's deterministic job (Criticality). Keywords: security
  posture, authn, authz, oauth, TLS, encryption, secrets, vault, production readiness, open risk.
allowed-tools: ["codebase", "search", "editFiles", "runCommands"]
metadata:
  version: 0.1.0
---

# sre-security-posture

Author a **needs-review** `SecurityPosture` for a scanned service — its authn / authz / encryption /
secret-handling controls and the open risks a reviewer must close — each grounded in cited code or
config. This activates the `SecurityPosture` kind via the same propose-don't-assert contract the
other Tier-B skills use.

## When to use this skill

- "What's this service's security posture / how does it handle auth and secrets?"
- "Fill the security section of the PRR."
- Alongside `sre-prr-review`, when a production-readiness review needs a security summary.

## Prerequisites

- A scaffolded run exists; the engine has emitted the `TechStack` (dependencies) and config facts a
  posture is read from. Start the artifact from [templates/security.skeleton.yaml](./templates/security.skeleton.yaml).

## The trust boundary (read this first)

You record controls you can evidence; you never assert a control you can't, and you never touch
severity or data classification:

1. **Every field is grounded.** `authn: oauth2` needs a cited dependency or config (a
   `spring-security-oauth2` / `passport` dep, an `oauth`/`oidc` config block); `encryption:
   tls-in-transit` needs a cited TLS/`server.ssl` setting; `secrets: externalized` needs a cited
   Vault/`valueFrom: secretKeyRef`/env reference. Read
   [references/security-fields.md](./references/security-fields.md). No evidence ⇒ it's an
   `openRisks` entry, not a claimed control.
2. **Never the values.** Record that a secret reference exists and where — never the secret's value,
   and never an excerpt that contains one. Cite the key/line, mask the rest.
3. **Data classification is the engine's, not yours.** Whether the service handles PII/PCI is
   deterministically detected and lives on the `Criticality` artifact. Cross-ref it; do not restate
   or override it here.
4. **needs-review, never severity.** A `SecurityPosture` is advisory: it informs a human review and
   never feeds the deterministic alert severity floor (only a grounded criticality tier does).

## Workflow

1. Read the `TechStack` dependencies and the service's config (security config, CI, manifest env).
2. Fill the skeleton's controls **only** where you can cite evidence:
   - `authn` — the auth mechanism (oauth2 / oidc / mtls / basic / none-found).
   - `authz` — the authorization model (role-based / abac / method-level / none-found).
   - `encryption` — transit/at-rest signals you can cite (tls-in-transit, kms-at-rest).
   - `secrets` — how secrets are supplied (externalized / vault / env / hardcoded-RISK).
   - `controls` — discrete safeguards present (e.g. `secret-scan`, `tls`, `dependency-audit`).
3. Put everything you **expect but can't evidence** into `openRisks` (e.g. "no at-rest encryption
   signal found — verify datastore config"). An honest gap is the point of this artifact.
4. Obey [references/provenance-rules.md](./references/provenance-rules.md); cross-ref the `Criticality`
   artifact for data classification.
5. Run `sre-kb run --target <repo> --run <id> --to-stage validate` and fix flagged items until the
   `SecurityPosture` is a clean `needs-review`.

## Gotchas

- **A hardcoded secret is an open risk, not a control.** If you see a literal credential, record it
  as a masked `openRisks` finding (location + type), never the value — and never mark `secrets`
  anything but a risk.
- **No evidence ⇒ open risk.** Don't infer `authz: role-based` from a service's importance; infer it
  from a cited `@PreAuthorize` / role config or leave it a risk.
- **Don't duplicate Criticality.** PII/PCI classification is the engine's; link to it, don't re-derive.
- The model is unset on purpose (LLM-neutral) — this skill works under any Copilot model.
