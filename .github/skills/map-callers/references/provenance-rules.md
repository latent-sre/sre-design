# Evidence & the governance block

You are the analyst: read the code, reason across files, and emit the artifact directly. Keep every
claim honest and traceable — but there is **no deterministic re-grounding gate** second-guessing you,
so this discipline is on you.

## Cite what you can

- Cite `path:line` (a real file + line range you actually read) for each material claim, so a
  reviewer or an on-call responder can jump straight to the code. Prefer a specific line to a bare
  file, and a bare file to nothing.
- Don't invent files, line numbers, metric names, log strings, thresholds, or SLO targets. A value
  that isn't in the code/config is either **inferred** (fine, when labelled) or fabricated (never).
- When a claim can't be grounded in code you actually read, mark it inferred and lower `confidence`;
  never dress an inference up as an observation.

## Every artifact carries the governance block

Emit these on every artifact so AI output stays auditable and is reviewed before it is trusted:

- `provenance: { repo, commit, scanDate, skill }`
- `ownership: app | platform | shared` — who owns the concern (app team vs platform vs shared).
- `confidence: high | medium | low` — how sure you are; `low` means "a human should look harder".
- `needs-human-review: true` — AI output is always human-reviewed; never set this `false` yourself.
- `unverified-against-live: true` — for anything you could not check against a live system (a
  threshold, an SLO target, an inferred dependency). Clear it only when a live signal confirms it.

## Honesty beats coverage

Distinguish `observedIn: code | config | inferred`. One evidenced finding ("no timeout on this
client, `src/…:42`") is worth ten hand-wavy ones. When unsure, classify toward the safer / more
severe reading, lower `confidence`, and leave it for a human — don't guess to look complete.
