# Phase 1 — adopt `resiliency-skills`' hardening

Phase 1's job (per `HYBRID-PLAN.md`) is to close the two named security weaknesses **before**
LLM breadth is added: the breakable injection fence and the publish path. Both are now fixed,
fail-closed, and tested. The larger "lift verbatim" items are consciously deferred (see end).

## 1. Unbreakable, nonce-bound untrusted-data fence (`security/fence.py`)

**Weakness (§4).** Untrusted target-repo code was fenced to the LLM with a *fixed* delimiter
pair — `<<<UNTRUSTED …>>> … <<<END UNTRUSTED>>>`. A hostile source file could simply contain
the literal `<<<END UNTRUSTED>>>` line and then write its own text, closing the fence early and
escaping into the "trusted" region. The path in the header was unescaped too.

**Fix.** `fence(content, meta=...)` binds each block to a fresh random **nonce**:

```
<<<UNTRUSTED 9f3a1c7b2d4e5f60 src/PaymentsClient.java:22-26>>>
…content, byte-for-byte…
<<<END UNTRUSTED 9f3a1c7b2d4e5f60>>>
```

The closing marker counts **only** when it carries that block's nonce, which the untrusted
content cannot predict — so any `<<<END UNTRUSTED>>>` inside the content is just data. A
`FENCE_INSTRUCTION` constant tells the model exactly that rule. Three design points:

- **Content is preserved verbatim** — not escaped or mangled. The gap-finder quotes these exact
  bytes back as anchors (Phase 4), so corrupting them would break grounding. Safety comes from
  the unguessable delimiter, not from rewriting the payload.
- **The header/meta is sanitised** (newlines and `<<<`/`>>>` stripped) — it is engine text, not
  a quoted anchor, so a path can't inject a delimiter.
- Wired into every place untrusted code reaches a model: `synth/context_pack.py` (Copilot
  enrichment), `synth/gap_prompt.py` (the gap-finder), and `validation/challenge.py`
  (`LLMChallenger`).

> This is the textual equivalent of `resiliency-skills`' architectural containment. Their scan
> agent holds no credential so a broken fence can't escalate; here the fence itself can't be
> broken. (The credential-less scan role is a deployment posture, deferred below.)

## 2. Publish path: token off argv + fail-closed allowlist

**Weakness (§4).** `open_pr` embedded the token in the remote URL passed to `git`
(`https://x-access-token:TOKEN@github.com/...`) — visible to `ps` and persisted in the repo's
remote — and had **no target-repo allowlist**, relying entirely on the ambient token's scope.

**Fix.**

- **Token off argv** (`publish/forge/github.py`): the token is written to a `0600`
  `.git-credentials` file in the per-run temp dir and supplied via
  `-c credential.helper="store --file=<path>"`. `git` argv now carries only the **clean** URL
  `https://github.com/owner/repo.git` and the *path* to the credential file — never the token.
- **Fail-closed allowlist** (`publish/policy.py`): a live publish is refused unless the target
  `owner/repo` is on an explicit allowlist (config `publish.allowed_repos` ∪ env
  `SRE_KB_ALLOWED_REPOS`). With no list configured, **every live publish is refused** with a
  message saying how to allow it. Dry-run is never gated — it writes nothing outside the work
  dir. Enforced at the `assemble_pr` choke point, so the engine — not just the token — decides
  the destination.

## Tests

`tests/test_phase1_hardening.py` (7): an embedded fake fence cannot close a block; fresh nonce
per call; meta sanitisation; context-pack fences are nonce-bound with payload retained; the
token never appears in any `git` argv (clean URL + credential helper used); live publish refused
with no allowlist; allowlist admits only listed repos.

Full suite: 122 passing, ruff clean.

## Consciously deferred (tracked, not done)

These are `resiliency-skills` items that are larger lifts and/or already partly mitigated here;
they are **not** required to close the two named weaknesses:

- **Sandboxed-Jinja / `json.dumps` renderers.** `sre-design`'s Mermaid renderer was already
  sanitised (§4 finding 4); a full safe-by-construction renderer pass across `render/` is its own
  workstream.
- **Second independent secret gate** (`detect-secrets` wrapper). One deterministic gate
  (`security/secret_scan.py`) already runs at publish; a second, differently-implemented gate is
  defense-in-depth, not a gap.
- **Credential-less scan role / fan-out cap / self-defending generated repo.** Deployment-posture
  and supply-chain items from `resiliency-skills`; orthogonal to the engine code changes here.
