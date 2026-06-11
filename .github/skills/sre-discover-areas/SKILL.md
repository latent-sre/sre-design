---
name: sre-discover-areas
description: >-
  Coverage-discovery (Tier-B) — propose NEW AREAS the engine never looked at. After a run,
  the engine writes a deterministic blind-spot ledger (reports/coverage.json): every file the
  scan walked that no fact cites, plus its own capability inventory. You judge which blind
  spots carry real SRE signal (migrations, Dockerfiles, IaC, cron syntax, nginx conf, …) and
  propose what the engine should learn to collect there. The ingest locates your evidence
  verbatim and refutes any area the fact set already covers; survivors become engine
  recommendations that graduate into new collectors. Use when asked what the engine missed,
  to audit scan coverage, or to recommend engine improvements after a run.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# sre-discover-areas

The loop the production runs asked for: don't just verify the engine's findings — find what
the engine **never looked for**, and turn it into engine growth.

## Inputs (closed-world ground, untrusted strings)

- `reports/coverage.json` in the run — the deterministic ledger: uncovered file groups with
  counts and sample paths, the registered kinds, detectors that fired, kinds never emitted.
- The uncovered files themselves (read them — your evidence must be verbatim bytes from one).

## The judgment you add

Most uncovered files are noise (docs, images, lockfiles, generated code) — restraint is the
value. A real area is repo content carrying operational risk or knowledge no fact captures:
database migrations, Dockerfiles/buildpacks config, IaC, cron/quartz definitions, proxy
configs, feature-flag rule files, data-retention policies. For each, say *what the engine
misses* and *what it should collect* (files to read, fact types, artifact kind).

## The non-circular contract

You **point**, the engine **judges**: your `evidence` is one line copied EXACTLY from an
uncovered file. The ingest (`sre-kb discover-areas --target <repo> --run <id>`) locates it
verbatim (unlocatable → dropped) and **refutes** any area whose cited files already produced
facts — the engine looked there; it is not a blind spot. Survivors are advisory engine
recommendations (`reports/engine-recommendations.{json,md}`), never artifacts.

## The flywheel

A reviewer confirms a recurring area with `sre-kb confirm-gap area-<name> --novel`; the
graduation tracker accrues it, and at the threshold `sre-kb graduation-candidates` drafts a
**new collector sketch** (globs, fact types, kind, registry row) — recommendations compound
into engine coverage, run over run.

## Emit

A JSON object written to `.sre/area-proposals.json`:

```json
{"areas": [
  {"name": "db-migrations",
   "files": ["db/migration/V7__drop_index.sql"],
   "evidence": "DROP INDEX idx_orders_customer;",
   "missing": "destructive DDL ships with no rollback or review trail in the KB",
   "proposal": "collect schema.migration facts from db/migration/*.sql (statement class, destructive flag) and roll them into a SchemaChange kind"}
]}
```

Reply `{"areas": []}` when the blind spots are noise.
