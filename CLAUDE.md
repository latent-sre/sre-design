# CLAUDE.md

Guidance for Claude Code (and any agent) working in this repo. Keep it short; link to
`docs/` for detail rather than duplicating it.

## Commands

```bash
make install   # pip install -e ".[dev]"
make test      # pytest -q     — must be green before you call work done
make lint      # ruff check src tests   — must be clean
make fmt       # ruff format src tests
```

Python ≥ 3.13 (the floor, the dev base, and what CI tests). CLI entrypoint is `sre-kb`. Tests live in
`tests/`.

## Branching & commits — use the standards

Follow [Conventional Commits](https://www.conventionalcommits.org/) for both branch names and
commit messages, with one shared type vocabulary.

**Always cut a new branch from the current tip of `origin/main`** — never from whatever commit a
session happens to open on:

```bash
git fetch origin main
git switch -c <type>/<short-kebab-summary> origin/main
```

**Types** (same for branches and commits):
`feat` · `fix` · `docs` · `refactor` · `test` · `chore` · `ci` · `perf` · `build` · `revert`

- **Branch:** `<type>/<short-kebab-summary>` — e.g. `feat/wavefront-adapter`,
  `fix/burn-rate-route-scoping`, `docs/claude-md`.
- **Commit:** `<type>(<optional-scope>): <imperative summary>` — e.g.
  `feat(render): add Wavefront alert adapter`, `fix(alerts): scope burn-rate to the flow route`,
  `docs: expand CLAUDE.md`.
- Bug fixes are `fix` (no separate `bug` type). Imperative mood, subject ≤ ~72 chars, no trailing
  period. Keep each commit focused on one logical change.

**Reviews especially** must branch from current `origin/main`: development moves fast, and a review
cut from a stale commit re-analyzes already-fixed code and "rediscovers" settled conclusions. (This
rule exists because a prior review ran on a base ~80 commits behind `main` and re-flagged
already-fixed bugs.)

## Working conventions

**Workflow**
- Run tests + lint before declaring work done; report failures honestly rather than hiding them.
- Keep changes minimal and scoped to the request — no opportunistic refactors or unrelated edits.
- Match the surrounding code's style, naming, and patterns; prefer editing existing files over
  adding new ones.
- Don't commit/push or open PRs unless asked. Never force-push a shared branch.

**Code quality**
- Add or update tests for any behavior change. Never weaken, skip, or delete a test just to make it
  pass.
- No dead code, commented-out blocks, or debug prints left behind.
- Prefer the standard library; justify any new dependency. Don't bump/pin deps as a side effect.
- Handle errors explicitly; don't swallow exceptions silently.

**Safety & correctness**
- Never commit secrets, tokens, or credentials. Treat external/user/target-repo input as untrusted.
- Don't delete or overwrite files you didn't create without first checking what's in them.
- Confirm before anything destructive or hard to reverse.
- If a request is ambiguous or you're guessing at intent, ask rather than assume.

**Communication**
- State what was actually done vs. skipped; flag assumptions and known limitations.
- Reference code as `file:line`.
