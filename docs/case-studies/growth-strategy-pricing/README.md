# Case Study — Pricing model: value-based vs seat-based (stub)

> **Demo engagement** · Stub · The full deliverable is on the roadmap. The stub session is seeded by `make demo` so you can see how a `growth_strategy` mode engagement appears in the homepage list.

---

## The question

> Should we shift from **seat-based** to **value-based** pricing for our enterprise tier?

**Report mode:** `growth_strategy` — Argus enforces market and capabilities research branches with a minimum of 2 evidence objects per branch.

---

## What this stub demonstrates

- The home page lists three distinct demo engagements, not just one.
- A `growth_strategy` engagement is interesting for Argus because it's typically more *internal-data-heavy* than a market-entry engagement — uploaded documents (usage logs, NRR cohorts, ACV bands) carry more weight than web research.
- The pipeline handles "minor" strategic questions (pricing change) and "major" ones (market entry, M&A) with the same machinery — only the consulting mode and the input mix change.

---

## Anticipated wedge of value

Value-based pricing decisions usually fail because:
1. Sales team incentives are misaligned with the new pricing axis.
2. The "value" metric is one customers can't predict at signup.
3. Existing customers grandfather under old pricing, splitting the book.

Argus would map each of these into a research branch + supporting evidence, and the `Critic` would explicitly challenge the recommendation against each failure mode before the report is finalized.

---

## See also

- [Germany vs France](../germany-vs-france/README.md) — full worked deliverable.
- [`backend/agents/critic.py`](../../../backend/agents/critic.py) — the critic prompt and revision-instruction format.
