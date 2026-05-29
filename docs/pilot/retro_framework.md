# Pilot retro framework

How to judge whether the pilot succeeded — because the pilot runs *beyond*
Week 25, and v1.0 shipping is **not** the same as the pilot succeeding.
v1.0 means "a real firm uses it, with documented bounds." Success is a
separate, measured verdict, rendered on the criteria below.

> **Hard line:** do not call the pilot "successful" until these criteria
> are met over a real evaluation window. "Launched and running" is a fact;
> "successful" is a finding.

---

## The success criteria

Five questions, in priority order. The first three are quantitative
(instrumentation already live, W24/W25); the last two are the ones that
actually decide renewal.

| # | Question | Signal / source | Bar |
|---|---|---|---|
| 1 | Is the verification trustworthy in production? | claim-feedback agreement rate; `wrong_supported` % (`pilot_health.claim_feedback_agreement`) | agreement ≥ 80%; **`wrong_supported` ≤ 5%** (the escalation class) |
| 2 | Does it produce usable drafts? | edit rate (`edit_rate_summary`) | avg edit ≤ 40%; **not** sustained > 60% |
| 3 | Are the deliverables good? | artifact ratings (`artifact_quality_signal`) | avg ≥ 3.5/5; no artifact type stuck < 3.0 |
| 4 | Would they keep using it? | weekly check-in `would_keep_using` | "yes", sustained |
| 5 | Would they pay for it? | direct conversation at the window's end | a real commercial yes/no |

A pilot that hits 1–3 but fails 4–5 is a *product that works but isn't
wanted* — a more important finding than any green metric.

---

## The cadence

- **Daily (operator):** the live-pilot view + alerts (W25/D2). Catch
  failures/anomalies in minutes; log every issue (`issue_log.md`).
- **Weekly:** the structured check-in (W24/D3 form) + a 1-paragraph
  operator summary to the firm. Update `learnings.md` with the week's
  edit-rate / agreement / rating numbers.
- **Evaluation window (recommend 4–6 weeks of real engagement volume):**
  the criteria above only mean something once enough real engagements
  have run. Below ~10 engagements the signals are directional, not a
  verdict — the aggregates carry a `low_sample` flag for exactly this.

---

## The decision points

At the end of the evaluation window, one of three calls:

1. **Continue / convert** — criteria 1–5 broadly met. Move to commercial
   terms; the post-1.0 roadmap is prioritized by what the signals flagged.
2. **Extend + fix** — the product works (1, 3) but a specific gap is real
   (e.g. edit rate high → draft quality; or over-flagging annoys). Run a
   targeted fix cycle, then re-measure. The pilot isn't failed; it's
   informative.
3. **Stop** — criteria 4–5 are a clear no, or criterion 1
   (`wrong_supported`) breached the safety bar. Document why honestly in
   `learnings.md`; that's the most valuable outcome a pilot can produce if
   it's true.

---

## What would change this framework

If the pilot's early signal materially shifts the picture — e.g. the firm
values something we didn't instrument, or the edit rate is dominated by
cosmetic reformatting rather than substantive rewrites — update these
criteria to measure what actually matters, and note the change here. The
framework serves the truth about the product, not the other way round.
