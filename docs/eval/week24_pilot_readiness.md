# Week 24 — Pilot readiness

**Status: ship**
**Pilot start: GREEN**

> Week 24 closes the gap between "system built" and "real firm can use it
> Monday." The real-claim calibration gate — deferred since Week 22 —
> landed at **0% FP-rate-on-supported, 100% recall-on-insufficient** on
> 61 human-labelled real engagement claims through the cross-family
> verifier. Onboarding flow, feedback instrumentation, an operator
> runbook, and a full end-to-end dress rehearsal (real pipeline, real
> verifier) confirm the system runs start-to-finish on a realistic
> scenario. Pilot posture: **"verified" (conservative)** — matches the
> W22/W24-D1 measured reality, no overclaiming.

## The real number

| Metric | Value | Posture |
|---|---|---|
| Real-claim FP-rate-on-supported | **0.0%** (0/7 supported predictions wrong) | GREEN |
| Recall-on-insufficient | **100%** (4/4 caught) | safety preserved (≥85%) |
| Real-claim recall-on-supported | 27% | conservative — under-credits, never over-credits |
| Labelled pairs | 61 | above the 40-pair gate floor |
| Edit rate (dress rehearsal) | 0% measured — **see note** | not yet a real signal (see below) |
| Dress-rehearsal LLM cost | $0.69 / 53 calls | well under the ~$1-2 estimate |

**Honest note on edit rate.** The dress rehearsal's review cycle
approved the memo **without making manual prose edits** to the payload,
so the measured edit rate is 0% — that reflects "no edits were made in
the rehearsal," NOT "the drafts need no editing." The real edit rate is
a **live-pilot signal**: it only becomes meaningful when real
consultants rewrite real drafts before approving. The instrumentation
(W24/D3 edit telemetry) is wired and verified; it will produce the true
number once the pilot runs. The runbook's success criteria
(edit rate ≤ 40%) is the bar to watch.

## Dress rehearsal — end-to-end on a realistic scenario

Runner: `tools/run_pilot_dress_rehearsal.py`. A fresh firm ("Pilot
Dress Rehearsal Inc") with 3 users + a 7-doc synthetic library (the
firm's own content — a mid-market 3PL target dossier, not Meridian
fixtures), two engagements run through the **real pipeline + real
cross-family verifier**. Result in
`backend/eval_runs/week24_dress_rehearsal/summary.json`: **all 9 phases
pass.**

| Phase | Result |
|---|---|
| Onboarding | firm + 3 users created via the operator path |
| Library | 7/7 docs ingested |
| Engagements | M&A diligence + growth strategy created |
| Pipeline (real) | M&A complete (10 verified claims, 286s); growth complete (20 verified claims, 459s) |
| Artifacts | 6/6 deliverables generated per engagement |
| Review cycle | submit → request_changes → resubmit → approve, all OK |
| Feedback | 6 claim assessments (4 correct, 2 wrong-flagged), 2 ratings (avg 4.0), 1 check-in |
| Enterprise | isolation 2/2 cross-firm attempts blocked; purge → 0 residual rows; audit export 5 rows, no content leak |
| Cost | $0.69 across 53 LLM calls |

The 2-of-6 "wrong-flagged" claim feedback mirrors the W24/D1 finding:
the verifier is conservative (it flags genuinely-fine claims for review)
but never wrongly blesses. That's the safe direction.

## Pilot-readiness sign-off checklist

| # | Item | Result |
|---|---|---|
| 1 | Real-claim FP rate within GREEN/YELLOW | ✅ GREEN (0%) |
| 2 | Recall-on-insufficient ≥ 0.85 | ✅ 100% |
| 3 | Onboarding flow completes end-to-end | ✅ dress rehearsal phase 1-2 |
| 4 | All 6 artifacts generate per engagement | ✅ 6/6 both engagements |
| 5 | Review cycle works end-to-end | ✅ submit→changes→resubmit→approve |
| 6 | Feedback instrumentation captures correctly | ✅ claims + ratings + check-in + telemetry |
| 7 | Observability dashboard shows real data | ✅ pilot-health panel returns real aggregates |
| 8 | Enterprise scenarios (isolation/deletion/audit/budget) pass | ✅ all pass |
| 9 | Smoke check all-green | ✅ 7/7 green (real verifier + real config) |
| 10 | Runbook + deploy requirements documented | ✅ W24/D4 |

**No RED items. Pilot starts.**

## Pilot framing — the honest claim (matches W22 posture)

What Argus claims to Blackmont, exactly as measured:

> Argus turns a partner's brief into a complete, **evidence-backed**
> consulting deliverable set, with a verification layer that — on our
> real-claim measurement — **never wrongly stamped an unsupported claim
> as "supported" (0% false positives) and caught 100% of the genuinely
> unsupported claims.** The trade-off is deliberate conservatism: it
> flags more claims for human review than strictly necessary, so a
> partner reviews before anything reaches a client. The posture is
> **"AI-assisted with human review on flagged claims"** — an honest,
> shippable first-pilot stance. We do not claim the verifier is
> infallible; we claim it errs on the safe side and that a human stays
> in the loop.

No overclaiming relative to measured reality: the verifier is
conservative, the edit rate is unmeasured until the live pilot, and a
human reviews every deliverable.

## What's deferred to post-pilot

- **SSO / SAML** — pilot runs on email + bcrypt session auth.
- **Application-level field encryption** — deploy-level at-rest
  encryption (managed DB + encrypted volumes) is the pilot-appropriate
  answer (W24/D4); app-level field encryption is a Phase 6/GA item, only
  if a buyer makes it a hard requirement.
- **External penetration test** — pre-GA, not pre-pilot.
- **Multi-region / HA** — not needed at pilot scale.
- **From Day 1's calibration:** the verifier's low recall-on-supported
  (27%) — i.e. its conservatism — is a known characteristic, not a bug.
  Reducing over-flagging without raising the false-positive rate is a
  post-pilot quality track, informed by the live per-claim feedback the
  W24/D3 instrumentation now collects.

## Week 25 starts with

**The actual pilot.** Onboard Blackmont (operator-assisted via
`tools/pilot_setup.py` + the runbook), ingest their real content, run
their first engagement, and watch the daily dashboard against the
runbook's thresholds. The first real signal to collect is the **true
edit rate** — the one number this rehearsal couldn't produce.
