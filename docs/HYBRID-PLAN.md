# sre-design ↔ resiliency-skills: comparison, findings, and a hybrid plan

A source-level comparison of this repo (`sre-design` / the `sre-kb` engine) with
[`latent-sre/resiliency-skills`](https://github.com/latent-sre/resiliency-skills)
(the `latent-sre` engine + Copilot skill suite), and a phased plan to combine their
strengths.

> Provenance of this doc: both engines were read in full from source (this repo locally;
> `resiliency-skills` from a fresh clone of `main`). Every claim below is grounded in a
> named file, not a README.

---

## 1. The headline difference: fat engine vs. fat skills

Both repos are from `latent-sre` and target the same goal — turn a service repo into a
populated, validated SRE knowledge base / `SRE-<service>` repo (Backstage catalog,
runbooks, SLOs, alerts, architecture). They make **opposite architectural bets** about
who does the extraction.

| | **this repo** (`sre-design` / `sre-kb`) | **`resiliency-skills`** (`latent-sre`) |
|---|---|---|
| Philosophy | Deterministic **fat engine**, thin LLM | "**Thin skills, fat config**, deterministic transforms" |
| Who extracts the facts? | The **engine**, via tree-sitter **AST** parsing | **Copilot**, via 18 granular LLM skills |
| Role of Copilot | Narrow: enrich scaffolds + adjudicate a challenge loop | Primary: scan / map / assess / generate artifacts |
| Engine ↔ LLM | "The engine **never calls an LLM**" | Engine is the deterministic post-processor for LLM output |
| # of Copilot skills | 1 (`sre-flow-analysis`) + 1 agent + 3 prompts | 18 (`assess-*`, `generate-*`, `map-*`, `publish-*`) |
| Languages today | Java/Spring + .NET/Steeltoe (AST collectors) | Any (LLM generalizes), PCF-focused |

They are essentially mirror images solving the same problem.

---

## 2. Verified findings

### Finding A — `resiliency-skills` has **no byte-level citation grounding**

Their full validation surface, read from source:

- `engine/src/latent_sre/validate.py` — **JSON Schema validation only** (Draft 2020-12):
  required fields, `additionalProperties: false`, enums. No source re-read, no hashing.
- `engine/src/latent_sre/assemble.py` — a **deterministic in-tree transform**: loads the
  already-scanned `.sre-scan/<service>/` YAML, copies/renders it, re-runs schema + redact
  gates. It never re-reads the target repo or hashes a cited excerpt.
- The only hashing in the engine is `engine/src/latent_sre/hashdiff.py`, and it is
  **clobber-protection** — it hashes the *output YAML* (provenance stripped) to avoid
  overwriting human edits, not source excerpts.

Their `provenance` block (required across every schema) is `repo, commit, scanDate, skill`
— **no `path`, no `lines`, no `excerptHash`.** Nothing in the loop ever asks *"do the cited
bytes actually contain this claim?"*

**Consequence:** a *confident* hallucination passes. A skill can emit a circuit-breaker
timeout with `confidence: high` and a syntactically valid provenance block, and
`validate.py` waves it through — schema-valid, well-attributed, and wrong.

Their anti-hallucination defenses are real but **soft / self-attested**:
- Copilot instructions: *"Never fabricate thresholds, SLO targets, or dependencies — if
  unknown, lower confidence and say so."*
- Skills label `observedIn: code|config` vs `inferred`; *"never assert a gap you cannot
  evidence."*
- Self-reported `confidence` (low/med/high) + `unverified-against-live: true`.

Every one of these is the model policing itself; schema validation only checks *shape*.

### Finding B — this repo **does** verify claims against source bytes

The exact gap above is what this repo closes:

- `src/sre_kb/collectors/base.py::hash_excerpt` computes `sha256` over the cited
  1-based line range; every `Evidence` carries `repo, commit, path, lines, excerptHash,
  detector` (required by `schemas/_envelope.schema.json`).
- `src/sre_kb/validation/provenance.py` **recomputes** that hash; a citation whose bytes
  don't match cannot pass — independent of what the model believed.
- `src/sre_kb/validation/challenge.py` + `pipeline/challenge_apply.py` add an adversarial
  grounding pass (monotonic, downgrade-only).
- `src/sre_kb/validation/gating.py::final_status` downgrades anything unverified to
  `needs-review` rather than dropping it.

**Net:** this repo's trust is *engine-verified*; theirs is *model-attested*.

### Finding C — `resiliency-skills` has the stronger **security boundary** + supply chain

This is where they are clearly ahead, and it is documented + enforced, not aspirational
(`docs/ownership-boundary.md`, `docs/publish-path.md`, `SECURITY.md`):

- **Two-role split** — the agent that *reads untrusted code* (scan role: read-only, no
  terminal, no network, no write token) and the credential that can *write* (publish role:
  CI, credential scoped to `latent-sre/SRE-*` only) **never share a context**. Injection
  has nothing to act on: the scan agent holds no credential, so "exfiltrate and open a PR"
  dead-ends.
- **The write path is deterministic, not agentic** — publish runs `assemble` (render /
  validate / redact / scaffold) and opens a PR; it never re-interprets the target, weakens
  a gate, fills a sentinel, or sets `needs-human-review: false`.
- **The generated `SRE-<service>` repo defends itself** — ships its own CI against
  *vendored pinned* `.sre/schemas`, `CODEOWNERS` (sentinel owner), a PR template, and
  clobber-protection (`.proposed/` instead of overwriting human edits).
- **Supply chain (enforced):** hash-pinned deps (`pip install --require-hashes`),
  digest-pinned GitHub Actions (Renovate), two independent secret gates (`redact` +
  `detect-secrets`), and an air-gapped offline wheel bundle for PCF runners.

This repo's equivalent is implicit (untrusted-input context packs in
`synth/context_pack.py`, a publish-time secret gate, a forge abstraction) but is **not**
a formalized scan/publish credential split.

### Finding D — secret gates: entropy-rich vs. deterministic-only

| | `resiliency-skills` `redact.py` | this repo `security/secret_scan.py` |
|---|---|---|
| Known patterns | ✅ (AWS, GH, Slack, JWT, PEM, bearer, URI-creds) | ✅ (similar set + jdbc-password, fine-grained PAT) |
| Entropy heuristic | ✅ Shannon ≥ 4.0 bits/char, len ≥ 20 | ❌ **deliberately omitted** ("avoid flaky false positives") |
| Value-shape rule | ✅ secretish-key: opaque-value | ✅ assigned-secret (quoted + unquoted) |
| Placeholder suppression | ✅ + sentinels (`REPLACE_ME__`) | ✅ placeholder regex |
| Allowlist | inline `# latent-sre:allow` + `.latent-sre-allow` | — |
| Fail-closed | ✅ (non-zero exit) | ✅ (`SecretLeakError`) |
| Second independent gate | ✅ `detect-secrets` in CI | — (single gate) |

Trade-off: theirs catches more (entropy) at some false-positive risk and double-gates;
this repo trades recall for determinism/stability and runs a single gate.

### Finding E — kind/schema coverage: graph-depth vs. breadth

Both emit `apiVersion`+`kind` artifacts with a governance block. Overlap is large; the
*shape* of the non-overlap is the interesting part.

- **Overlapping kinds:** architecture, dependencies, slo, tech-stack, resiliency,
  runbook, alert, observability, api-contracts/interface, pcf-deployment/deployment.
- **This repo is deeper on the call/flow graph:** `Flow` (request sequence flows),
  `Topology` + `estate` (cross-service co-tenancy), `BlastRadius`, `Fallback`,
  `DataStore`, `ConfigManagement`, `ReadinessScore` (PRR grade), plus `diff` (drift) and
  `findings` (ranked risk digest).
- **`resiliency-skills` is broader on coverage surface:** first-class `dashboard`, `jobs`,
  `delivery`, `criticality`, `messaging`, `infrastructure`, `logging` as separate concerns,
  and multi-tool alert `render-adapters` (Splunk / Wavefront / AppDynamics / Prometheus —
  beyond this repo's current Splunk + Prometheus).

---

## 3. Which is "better"?

Neither, unconditionally — they optimize different axes:

- **Correctness / reproducibility / auditability → this repo.** AST extraction is
  deterministic and re-runnable; claims are grounded to `path:line` + recomputed hash.
- **Breadth / maintenance-to-grow / security boundary → `resiliency-skills`.** LLM skills
  generalize to any stack without writing a parser; the scan/publish split is the more
  mature containment design.

**Pick by estate:** mostly Java/.NET and correctness-critical → this repo; polyglot and
breadth-first → `resiliency-skills`. But the strongest system is the **hybrid** below.

---

## 4. The hybrid plan

**Thesis:** keep `resiliency-skills`' skill-driven breadth *and* security boundary, but
fence the LLM output behind **this repo's byte-level grounding + 5-layer validation**. The
single highest-value move is forcing the LLM skills to emit `path:line` citations that
*this engine recomputes* — converting "trust the model's confidence" (Finding A) into
"verify the bytes" (Finding B).

This is mostly *adding a second kind of collector*, because the repo already pivots on the
right seam: a language-neutral `Fact` with provenance (`models/facts.py`) that collectors
emit and the scaffolder consumes. AST collectors and LLM skills can both produce `Fact`s;
everything downstream (scaffold → validate → render → publish) is unchanged.

### Trust tiers

Ride a trust tier on the existing `Evidence.detector` provenance:

- **Tier A — AST collectors** (existing): deterministic, high-trust. Java/.NET today.
- **Tier B — LLM skill collectors** (new, from `resiliency-skills`): broad-stack,
  lower-trust, **cannot reach `verified`** until grounded against cited bytes.

A router picks Tier A where a tree-sitter grammar exists and falls back to Tier B
otherwise. On overlap, **AST wins** (deterministic beats generated); Tier B only fills
gaps AST can't reach (documented limits: non-literal Kafka topics, cross-file call graph).

### Phases

| Phase | What | Effort | Risk |
|---|---|---|---|
| **0. Fact contract & trust tiers** | Add `source_tier: ast\|llm` to `Fact`/`Evidence`; define a `CollectorProtocol` (`collect(ScanContext) -> FactSet`) both tiers satisfy. No behavior change. | S | low |
| **1. Security boundary** | Adopt `resiliency-skills`' scan/publish split: scan role = read-only, **no `GITHUB_TOKEN`**, consumes only `synth/context_pack.py` packs; publish role = CI, holds the `SRE-*`-scoped credential, runs `publish/forge/github.py`. Assert the token is absent during scan (a test fails if scan can see it). | M | low |
| **2. LLM collector fallback** | `collectors/llm/`: build a context pack → invoke a Copilot skill → parse output **back into `Fact`s with full provenance**. Clone `.github/skills/sre-flow-analysis/` into the granular skill set (`map-architecture`, `assess-resiliency`, …). One end-to-end stack (e.g. Node/Express). | L | med |
| **3. Trust-tiered gating** | Extend `validation/gating.py::final_status`: a doc whose evidence is all Tier B cannot be `verified` unless it passed the challenge/grounding loop. The engine recomputes `excerptHash` for Tier B citations — a hallucinated citation can't pass `validation/provenance.py`. **This is the whole reason the hybrid is safer than either parent.** | M | low |
| **4. Render-adapter breadth** | Generalize `render/` to neutral-intent → adapter; add Wavefront / AppDynamics emitters (already on this repo's roadmap). | M | low |
| **5. Router & precedence** | Per-file/per-stack router (AST if grammar present, else LLM; AST wins on overlap). `findings` shows tier provenance per claim. | S | low |

**Sequencing:** 0 → 1 → 3 is the trust spine (low-risk, extends existing code) and lands
first. Phase 2 is the only heavy lift and the only new LLM-integration risk. Phase 4 is
independent and can run in parallel.

### The load-bearing contract

The discipline that makes Tier B safe: **the LLM proposes a claim + a `path:line`
citation; the engine recomputes the hash from those lines and rejects the claim if the
bytes don't match.** That single rule (Finding B applied to Finding A) keeps the breadth
of `resiliency-skills` from being a hallucination hole.

### Worth lifting verbatim from `resiliency-skills`

- The ownership/credential boundary (`docs/ownership-boundary.md`) — copy faithfully.
- Self-defending generated repo (vendored pinned schemas, own CI, CODEOWNERS, PR template).
- Supply-chain posture (`--require-hashes`, digest-pinned Actions, second `detect-secrets`
  gate, air-gapped bundle).
- `render-adapters` multi-tool alert breadth.

### Worth keeping from this repo

- Byte-level provenance (`hash_excerpt`) + the adversarial challenge loop — the grounding
  layer they lack.
- `Flow` / `Topology` / `estate` / `BlastRadius` graph depth.
- `findings` (ranked risk) and `diff` (drift).
