# Case Study — ExampleCo M&A diligence (stub)

> **Demo engagement** · Stub · The full deliverable is on the roadmap. The stub session is seeded by `make demo` so you can see how a `due_diligence` mode engagement appears in the homepage list.

---

## The question

> Evaluate **ExampleCo** as an acquisition target given recent revenue compression and pending litigation.

**Report mode:** `due_diligence` — Argus enforces financial, legal, and operational research branches with a minimum of 3 evidence objects per branch ([`backend/config/consulting_modes.yaml`](../../../backend/config/consulting_modes.yaml)).

---

## What this stub demonstrates

- The home page surfaces multiple in-flight engagements, not just one.
- A `due_diligence` mode session has different research branch requirements than `market_entry`.
- A draft session can be re-run from the workspace once an `OPENAI_API_KEY` is provided.

---

## To produce the full deliverable

1. Run `make demo` — the stub session appears on the homepage with status `draft`.
2. Set `OPENAI_API_KEY` in `.env` and re-up the stack.
3. Click into the engagement → upload a 10-K excerpt or a litigation summary → click **Run pipeline**.
4. The full pipeline produces a deliverable mirroring the structure of [Germany vs France](../germany-vs-france/README.md).

---

## See also

- [Germany vs France](../germany-vs-france/README.md) — full worked deliverable showing what an Argus output looks like end-to-end.
- [`backend/config/consulting_modes.yaml`](../../../backend/config/consulting_modes.yaml) — the branch enforcement that differs between modes.
