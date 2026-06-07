# CLAUDE.md

Guidance for Claude Code (and any agent) working in this repo.

## Reviews must start from current `origin/main`

When asked to do a **review**, **comparison**, or **assessment** (of this repo, of a sibling
repo, of a hybrid plan, etc.), always base the work on the **current tip of `origin/main`** —
never on whatever commit the session happens to open on.

Procedure at the start of any review:

```bash
git fetch origin main
git switch -c <review-branch> origin/main
```

**Why:** development moves fast on `main`. A review branch cut from a stale commit will
re-analyze code that has already been fixed or superseded, and will "rediscover" conclusions
that are already committed. Reviewing against current `main` is the only way the findings are
about the code as it actually stands. (This rule exists because a prior review was accidentally
done on a base ~80 commits behind `main` and re-flagged already-fixed bugs.)

This applies to the analysis baseline regardless of which branch a task description names for the
final push — fetch and read current `main` before drawing conclusions.
