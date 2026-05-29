# Pilot learnings (living doc)

What the live pilot is teaching us — the quantitative signals (edit rate,
claim-feedback agreement, artifact ratings) plus the qualitative check-in
and issue log. This is the artifact that informs whatever comes after the
25 weeks. Update it as the signals accumulate; don't wait for a clean
narrative.

> **Status:** instrumentation live; awaiting real engagement volume. The
> numbers below populate from real usage — they are deliberately empty
> until the firm's engagements accumulate. The dress rehearsal (W24/D5)
> proved the plumbing; only real consultants editing real drafts produce
> the signal that matters.

---

## 1. Edit rate — the product-fit signal

**The question:** how much does a real consultant edit Argus's output
before delivering it to their client?

- **< 20% edited** → usable drafts; the leverage wedge holds.
- **20–50%** → useful first draft that needs real editing.
- **> 50%** → a starting point, not a deliverable. This would be the
  single most important finding of the pilot — documented straight, not
  spun. A high edit rate isn't failure; it's the truth about where the
  product is.

Source: `engagement_edit_telemetry` (the diff between the auto-generated
v1 payload and the approved payload). We store the *fraction* + *which
sections*, never the prose (W20 privacy line).

| Metric | Value | Read |
|---|---|---|
| Avg edit rate (firm) | _pending_ | |
| Median edit rate | _pending_ | |
| Distribution (<20 / 20–50 / >50) | _pending_ | |
| Most-edited section | _pending_ | where the drafts fall short |

**Caveat to watch (W25/D3 surfaced):** the word-level diff can be
inflated by cosmetic/formatting edits. The current metric ignores pure
whitespace (it diffs non-whitespace tokens), but a consultant
reformatting a list still reads as churn. If the rate looks high,
sanity-check whether it's substantive rewriting or reformatting before
calling it a product-fit finding. A substantive-vs-cosmetic classifier
is a Phase-6 refinement.

## 2. Claim-feedback agreement — the live calibration signal

**The question:** of the claims consultants reviewed, how often did they
agree with the verifier's verdict? This is the production version of the
W24/D1 calibration gate — real consultants, real claims, continuously.

| Metric | Value | Read |
|---|---|---|
| Agreement rate (correct / decided) | _pending_ | |
| wrong_supported % (missed false positive) | _pending_ | **escalation class** |
| wrong_flagged % (over-caution) | _pending_ | expected (W24/D1 conservatism) |

This stream is **human-judged labeled data** — treated with the same
ground-truth care as the W24 labeling. It's the seed corpus that could
improve the verifier in Phase 6. `wrong_supported` is the one to watch:
the W24/D1 gate measured **0%** on the labeled set, so any real-world
`wrong_supported` is a signal worth a close look.

## 3. Artifact quality — the targeted improvement signal

**The question:** which of the six deliverables does the firm rate
highest / lowest?

| Artifact | Avg rating | Count |
|---|---|---|
| memo / one_pager / deck / excel_model / email / interview_guide | _pending_ | |

A split (e.g. memo rates well, deck rates poorly) is a targeted
improvement signal, not a blanket "artifacts need work."

## 4. Weekly check-in — the qualitative complement

The W24 structured check-in (`/pilot/checkin`). Record each week's
responses here as the qualitative read on the quantitative signals.

| Week | What worked | What didn't | Top friction | Trust (1-5) | Keep using? |
|---|---|---|---|---|---|
| _W1 pending_ | | | | | |

## 5. Cross-cutting findings

Pulled from the issue log (`docs/pilot/issue_log.md`) + the signals
above. The honest synthesis of what the pilot is teaching us.

- _pending first real engagements_

## 6. Implications for after the 25 weeks

What these signals imply for the product direction — to be written once
there's enough real data to draw a line, not before. Candidate Phase-6
threads already visible: substantive-vs-cosmetic edit classification;
using the claim-feedback stream as verifier training data; reducing the
verifier's over-flagging (the W24/D1 conservatism) without raising the
false-positive rate.
