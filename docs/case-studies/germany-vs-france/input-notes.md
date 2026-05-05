# Inputs — Germany vs France

## What the user provided

| Type | Item | Notes |
|------|------|-------|
| **Question** | Germany vs France market-entry framing | See [prompt.md](prompt.md) |
| **Constraints** | 18-month horizon, $2.5M budget, 12 HC, GDPR posture | Captured via intake |
| **Documents** | (none in this demo) | The pipeline is robust to zero uploaded files — it falls back to web research |
| **Report mode** | `market_entry` | Triggers branch enforcement |

> In a real engagement, the user would typically upload internal market research, a board memo, an investor update, or a competitive analysis. Argus chunks these via `backend/core/chunker.py`, embeds them with OpenAI `text-embedding-3-small` (1536-dim), and merges them with web evidence at retrieval time.

---

## What the planner generated

Six research tasks across three branches:

| Task | Branch | Question |
|------|--------|----------|
| 1 | market | How do the German and French B2B SaaS markets compare on size and growth? |
| 2 | market | What is the structure of mid-market ICP density in each country? |
| 3 | regulation | What are the GDPR and data-residency expectations of buyers in each country? |
| 4 | competition | What are the cost-of-presence and procurement cycle differences? |
| 5 | competition | How does sequenced vs parallel market entry perform at this team size? |
| 6 | market | What are post-landing retention and pilot success patterns? |

Decision criteria the planner committed to:
1. Market size
2. Growth rate
3. Procurement cycle length
4. Net revenue retention
5. GTM cost
6. Compliance fit

---

## What the researcher gathered

**14 web queries** executed in parallel across the 3 branches. **10 evidence objects** persisted to `evidence_objects`, drawn from **9 sources**. Zero contradictions detected.

| Branch | Queries | Evidence collected |
|--------|---------|--------------------|
| market | 5 | 4 objects |
| regulation | 3 | 2 objects |
| competition | 6 | 4 objects |

Top sources by source_score:
1. Bitkom — German Software Market Outlook 2024 (0.92)
2. Numeum — French SaaS Market Report 2024 (0.88)
3. UGAP — 2024 Annual Report (0.86)
4. Forrester — European B2B Buying Behavior (0.84)
5. Mercer — European Compensation Benchmarks 2024 (0.83)

---

## What the user did *not* need to do

- No prompt engineering — `IntakeAgent` generated the right clarifying questions.
- No source curation — `Researcher` ran query expansion and triage automatically.
- No format wrangling — the writer's output goes straight into the consulting-grade template.
- No verification step — `Verifier` runs automatically and surfaces verdicts in the trust rail.

The user's job is to ask a real question and answer 3 intake questions honestly. Argus does the rest.

---

## Raw fixture references

For an engineer who wants to see the underlying data:

- [`backend/tests/fixtures/germany_vs_france/session.json`](../../../backend/tests/fixtures/germany_vs_france/session.json) — session metadata + intake
- [`backend/tests/fixtures/germany_vs_france/evidence.json`](../../../backend/tests/fixtures/germany_vs_france/evidence.json) — 10 evidence objects
- [`backend/tests/fixtures/germany_vs_france/agent_outputs.json`](../../../backend/tests/fixtures/germany_vs_france/agent_outputs.json) — per-stage durations and token counts
- [`backend/tests/fixtures/germany_vs_france/pipeline_events.json`](../../../backend/tests/fixtures/germany_vs_france/pipeline_events.json) — SSE event stream
