# sre-design — SRE Knowledge-Base Generator (`sre-kb`)

A repo-neutral engine that performs a deep SRE review of a target code repository and
emits a **populated, validated SRE knowledge base** as schema-tagged YAML (`apiVersion`
+ `kind`), then projects it into **GitHub Copilot** skills/agents and opens a PR into a
company SRE repo.

Two halves:

- **Python engine (`sre_kb`)** — the *deterministic* half: scans a locally-cloned repo,
  extracts facts with hard provenance (`path:line` + commit + `excerptHash`), scaffolds
  artifacts, **validates** them (schema + provenance + cross-ref + gating), renders
  projections, and publishes.
- **GitHub Copilot in VS Code** — the *LLM* half (the only approved LLM): its agent mode
  enriches the scaffolded artifacts, driven by the Agent Skills / custom agent / prompt
  files this repo ships. The engine **never calls an LLM**.

The full design lives in [`docs/DESIGN.md`](docs/DESIGN.md).

## Status

Early scaffold (Phase 0 — walking skeleton). See `docs/DESIGN.md` → *Vertical slice*.

## Quickstart (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
sre-kb schema list          # introspect the kind registry
pytest -q                   # run the test suite
```
