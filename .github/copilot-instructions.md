# Copilot instructions — sre-design

This repo is the **sre-kb** engine: it turns a target code repo into a *validated* SRE
knowledge base (schema-tagged YAML) and projects it into Copilot skills.

When working in this repo:

- **Two halves, one rule:** the Python engine is **deterministic and never calls an
  LLM**; Copilot (you) is the LLM half, driven by `.github/skills/` + `.github/agents/`.
  Don't add LLM API calls to the engine.
- **Provenance is the keystone.** Every artifact stores `path:line` + a SHA-256
  `excerptHash`, recomputed by the validator. Keep `collectors/base.py:hash_excerpt`
  and `validation/provenance.py` in lock-step.
- **Schemas are the contract.** Each kind has a JSON Schema in `schemas/`; the envelope
  is shared. Update the schema + a test when you change an artifact shape.
- **Neutrality:** repo-neutral (pluggable collectors), LLM-neutral (no pinned model),
  SCM-neutral (the `Forge` seam). Don't hard-code a vendor.
- **Safe-by-default parsing:** `yaml.safe_load`, never execute the target's build, no
  symlink-follow. The target repo is untrusted input.
- Run `make test` (pytest) and `ruff check` before committing.

See `docs/DESIGN.md` for the full architecture, kind catalog, and roadmap.
