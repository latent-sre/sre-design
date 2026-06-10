# Business case: approve Google Vertex AI as a programmatic LLM provider for the SRE engine

> **Decision (2026-06): not pursued.** The org standardizes on VS Code Copilot +
> GitHub; the LLM seam stays the manual file exchange and no programmatic provider is
> wired (NEXT-INCREMENTS §3.1). Kept for the record should that decision be revisited.

Date: 2026-06-09
Status: **draft for approval** — the engine works today on enterprise GitHub Copilot (IDE-only); this
case requests an *additional, automatable* endpoint to lift the adoption ceiling.

## The ask

Approve **Google Vertex AI (Gemini) within our own GCP tenant** as an org-sanctioned endpoint the SRE
engine may call programmatically for its LLM half — scoped initially to a pilot (one project, a
bounded set of services). We already have Vertex access; this case is the data-governance and
cost/benefit justification to use it from automation rather than only via Copilot in the IDE.

## Problem this solves

The engine's deterministic half scans an application repo and produces a validated SRE knowledge base.
The **LLM half** (recall + judgment: resiliency gaps, messaging/log assessment, "where can this flow
fail") today runs **only through GitHub Copilot in the IDE** — a human opens VS Code, runs each skill,
and saves output files. That is fine for one service interactively, but it is the **adoption ceiling**:

- It cannot run in **CI** or on a schedule.
- It cannot **fan out** across many services (a portfolio scan is N manual sessions).
- The **converging discover→confirm loop** and the **accuracy eval harness** (HYBRID-PLAN §9.7 S4/S5)
  require repeatable, automatable model calls — impossible by hand at scale.

The unified scan worklist (S6, shipped) makes the manual loop one front door, but it is still manual.
A programmatic, approved endpoint removes the ceiling without changing the engine's design.

## Why Vertex specifically

- **Already available to us** — no new vendor onboarding; the gap is policy, not access.
- **In-tenant data governance** — calls stay in our GCP project under our IAM; Vertex offers data
  residency, customer-managed encryption, and **enterprise terms under which prompt/response data is
  not used to train Google's models**. Private connectivity (VPC Service Controls / Private Service
  Connect) keeps traffic off the public internet.
- **Model-neutral by design** — fits the engine's existing "no pinned vendor" stance; Gemini is one
  `LLMProvider` impl, not a lock-in (see architecture below).

## What data is sent (and what is not)

- **Sent:** small, fenced excerpts of target source the engine already assembles into context packs —
  the *same* content Copilot receives today. Untrusted target text is wrapped as data, never
  instructions (`synth/context_pack`, the injection fences).
- **Minimized:** only the bytes a task needs (the candidate call sites / claims), not whole repos.
- **Never sent:** secrets — the engine's `secret_scan` gate plus the independent `detect-secrets`
  CI gate run before any handoff; the publish path is fail-closed on detected secrets.
- **Note:** source already leaves our boundary *today* via Copilot (also a cloud LLM). Vertex-in-tenant
  is a **stronger** governance posture than the status quo, not a weaker one.

## Architecture — bounded, reversible, trust-preserving

A thin `LLMProvider` seam (mirroring the existing SCM-neutral `Forge` seam and pluggable collectors).
**The seam groundwork is built** (`src/sre_kb/llm/provider.py`) — only the Vertex impl is gated on
this approval:

- **Default impl is unchanged and shipped:** `CopilotFileProvider` (today's IDE file exchange) — it is
  **model-free** (`complete()` raises so the engine defers to the manual worklist loop). No provider
  configured ⇒ the engine behaves exactly as now.
- **Subprocess impl shipped:** `SubprocessProvider` execs an operator-configured CLI (the existing
  `--oracle` seam, now built through `make_provider`).
- **New impl (this ask):** `VertexProvider` — a **deferred slot already in the seam** (`complete()`
  raises with a pointer to this doc until approved). It will consume the **same** `scan-worklist.json`
  tasks and the same `SKILL.md` prompts, calling Vertex instead of waiting for a human. Swapping
  transport changes nothing else.
- **The trust boundary does not move:** the LLM remains a **pointer-generator** — it cites verbatim
  bytes; the engine re-grounds every output deterministically and gates it. An automated call cannot
  assert a verdict the engine trusts.
- **Reproducibility is preserved and built:** `CachingProvider` already wraps any provider with a
  **prompt-hash response cache** (sha256(prompt) → response on disk). With model pinned + temperature
  0, CI replays the cache; only an explicit refresh (delete the cache) hits the model — so the engine
  stays deterministic and testable.

## Benefits

- **CI + scheduled scans** of the whole portfolio, not one-at-a-time IDE sessions.
- **Service fan-out** — scan many repos in one run.
- **The discover→confirm loop and accuracy eval harness become real** (S4/S5), which is the gate to
  trusting/publishing output (the maturity curve in `SCOPE-AND-COVERAGE.md`). The instrumentation
  already runs in CI today: **12 labeled fixtures hold recall = precision = detector recall = 1.0**
  on the deterministic scorecard, and the gap-channel harness holds **5/5 kept recall and 1.0 kept
  precision** (including one out-of-taxonomy open-discovery case) with both negative controls
  rejected — so a model regression under automation is a red build, not drift. Stage-2 entry floors
  for real services are defined in `SCOPE-AND-COVERAGE.md` §3 and double as this pilot's success
  criteria.
- **Throughput** — removes the human bottleneck on the recall/judgment work.

## Cost

Token-based, and **low after caching**: most cost is the first scan of a service; re-scans replay the
cache except where code changed. Bounded further by the gap-finder **noise budgets**
(`gap_finder.max_candidates`, `gap_finder.max_novel`) and minimized context packs.

**Measured baseline (2026-06-09, from the engine's own labeled fixtures):** a full validated run
emits **~7k–16k input tokens per service** of LLM-facing material (all discover context packs +
challenge/confirm worklist items; chars/4 estimate — e.g. `sample-spring-pcf` 47 files ≈ 15.7k
tokens, `sample-dotnet-steeltoe` 37 files ≈ 10.4k). Fixtures are deliberately small; budgeting
**5–20× for a real service (~50k–300k input tokens first scan)** is the conservative planning
figure, with outputs (anchored JSON verdicts/proposals) an order of magnitude smaller. At current
enterprise Gemini pricing that is **well under a dollar per service first-scan**; re-scans replay
the prompt-hash cache. Compare against the alternative: skilled engineer-hours doing the manual IDE
loop per service, which does not scale and is far more expensive per service at portfolio size. The
pilot replaces these estimates with exact per-service figures.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Source data leakage | In-tenant Vertex, enterprise no-train terms, VPC-SC/private endpoints; secret gates run pre-handoff; context minimized |
| Prompt injection from hostile target code | Existing untrusted-data fences + sanitizers; the LLM is read-only and a pointer-generator; engine re-grounds |
| Cost runaway | Noise budget + per-run caps + prompt-hash caching; pilot establishes the figure before scale |
| Model drift / non-reproducibility | Pin model version, temperature 0, cache by prompt-hash; eval harness detects regressions |
| Vendor lock-in | `LLMProvider` seam is provider-neutral; Copilot path stays; another provider is another impl |

## Recommendation

Approve a **scoped pilot**: Vertex/Gemini in our GCP tenant, the `VertexProvider` impl, run over a
handful of services in CI. Success criteria: (1) per-service token cost within the budgeted figure
above, (2) the stage-2 accuracy floors of `SCOPE-AND-COVERAGE.md` §3 (kept precision ≥ 0.9, kept
recall ≥ 0.75, zero false positives surviving to `verified`, novel-channel confirmed share ≥ 0.5),
(3) zero secret/data-governance findings.
On success, expand to portfolio scanning. The engine stays Copilot-IDE-capable throughout, so this is
additive and reversible.

> Until this is approved, the engine remains Copilot-IDE-only and we optimize the manual path (the
> unified `scan-worklist.json` + the `sre-target-scan` agent). See HYBRID-PLAN §9.7 (S4/S5/S6).
