# The build — Argus, 25 weeks

The honest retrospective of the whole thing: what got built, the moments
it nearly went sideways, what the numbers say, and what's still genuinely
unknown. Written at the v1.0 cut — a real firm using it, with documented
bounds — not a victory lap.

---

## What got built — the five phases

**Phase 1 — the verification spine.** The wedge: nothing leaves the
system unverified. Claim-level source binding (the analyst literally
cannot serialize an ungrounded claim); cross-family verification (the
model that writes a claim is never the model that verifies it), enforced
at boot; a three-signal NLI ensemble (LLM judge + DeBERTa-v3 cross-encoder
+ lexical/numeric overlap) that only ever downgrades. Real retrieval from
SEC EDGAR, Companies House, transcripts, news, and firm-uploaded content.

**Phase 2 — firm knowledge + layered modes.** Argus stops being generic.
A per-firm library (firm-scoped, never cross-leaking) becomes a
first-class retrieval source. Layered consulting modes (built-in ← firm ←
engagement), M&A diligence as the first deal-shaped mode, structured
frameworks (2×2, Pyramid, MECE, Porter's, Value Chain) populated from
verified claims, and the section-deepening agent.

**Phase 3 — the six-artifact suite.** One verified claim base renders six
deliverables: memo, 1-pager, deck (PPTX), Excel model (XLSX), client
email, interview guide. Mode-aware structure, firm branding, cross-sheet
Excel formulas with citation comments, attachment-aware emails. Each
artifact re-checks every claim against the source registry before
rendering — defense in depth.

**Phase 4 — the collaboration layer.** Five interlocking workstreams:
review workflow (draft → in_review → changes_requested → approved →
delivered) with lock-on-approval; comments anchored to
section/claim/artifact/text-range with orphan detection; per-section
ownership + tasks + a my-work queue; notifications with actor-exclusion +
dedup; and version history with diff + approval-aware restore.

**Phase 5 — quality, observability, enterprise, pilot.** The trust claim
got measured (not asserted); observability got built so a failure is
debuggable in minutes; the four enterprise pillars (isolation, retention,
audit export, cost governance) landed; and the system was deployed and
put in front of a real firm with onboarding, a runbook, live monitoring,
and feedback instrumentation.

---

## The hard moments (the real story)

**The Week 7–8 iterate spiral — verifier stochasticity.** The verifier's
verdicts weren't stable run-to-run; the same claim could land
"supported" once and "weak" the next. Chasing determinism through the
ensemble + aggregator (only-downgrade, sticky-when-the-LLM-says-weak) was
a multi-day spiral before the behavior was predictable enough to build on.

**The Week 21 quality finding — the 0.60 that was a ghost.** Calibration
showed a 60% false-positive-rate-on-supported and the instinct was "the
verifier is broken, this isn't shippable." It turned out the number was
measured on the `heuristic_no_keys` fallback verifier — every W21/W22
calibration had been running heuristic-mode, not the real cross-family
ensemble. The "broken verifier" was a measurement ghost. Wiring the real
ensemble (the W22 Fix-Day) dropped synthetic FP from 43.75% → 0%. The
lesson: a scary number is worthless until you know exactly what produced
it.

**The labeling deferred three times.** The one irreducible human step —
Yassin hand-labeling real claim/evidence pairs to measure the *production*
FP rate — got deferred at W22/D1, again at the W22 Fix-Day, and was still
formally pending at the end of Week 24's start. It was the gate the whole
trust claim rested on, and it couldn't be automated (using an LLM to label
whether the LLM verifier is right is circular). It finally landed at
W24/D1: 61 real claims, labeled by hand, scored through the real verifier
— **GREEN**. Three deferrals, then the number that mattered.

**Three production-shaped CI/deploy failures in a row (W24→W25).** A lint
rule the local typecheck didn't run; a live-DB test suite CI ran without a
database; an app module importing from `tools/` that wasn't in the
container image. All the same root cause: the dev environment was more
permissive than production. The fix wasn't just the three patches — it was
reproducing the real CI/container conditions before claiming green.

---

## What the numbers say

- **~750 automated tests** (the DB-free CI tier) + the live-DB suites.
- **51 database migrations**, applied idempotently to a managed Postgres
  via a tracked runner.
- **The verifier, on real claims:** 0% false-positives-on-supported,
  100% recall-on-insufficient, on 61 hand-labelled claims through the
  cross-family ensemble — **GREEN**.
- **The six deliverables**, generated end-to-end on real content in the
  dress rehearsal (6/6 per engagement) at ~$0.35/engagement.
- **The full collaboration stack**, exercised end-to-end (submit →
  request-changes → resubmit → approve, with version history + edit
  telemetry).
- **The four enterprise pillars**, each with passing isolation /
  deletion / audit / budget scenarios.

---

## What's honestly still unknown

- **The edit rate.** The single most important signal — how much a real
  consultant rewrites Argus's output before delivering it — could not be
  measured before real usage. The instrumentation is live; the number is
  the pilot's to reveal. A high edit rate would be the most important
  finding, not a failure to hide.
- **Real-firm scale.** Everything is proven at pilot scale (one firm,
  a handful of concurrent engagements). Multi-instance/HA behavior under
  real load is untested by design (out of 1.0).
- **The conservative-verifier trade-off in practice.** The verifier
  over-flags (recall-on-supported ~27%). Whether that's an acceptable
  "human reviews a few extra claims" or an annoying "it flags everything"
  is a real-usage question the live claim-feedback stream will answer.

---

## What comes next (post-1.0, pilot-driven)

The roadmap is named in [`scope.md`](scope.md); the *priority* among
those items is set by what the pilot teaches:

- If the edit rate is high → draft-quality work (likely the writer +
  mode schemas) jumps the queue.
- If the claim-feedback stream shows real `wrong_supported` cases →
  verifier work, using that stream as labeled training data.
- If the over-flagging annoys consultants → the recall-improvement track
  (reduce flags without raising the FP rate).
- The standing post-1.0 list otherwise: SSO/SAML, app-level field
  encryption, external pen-test/SOC 2, Companies House OCR, multi-instance
  /HA, notification digests + push, finer-grained artifact anchoring.

Success of the pilot is judged separately — see
[`../pilot/retro_framework.md`](../pilot/retro_framework.md). v1.0 is the
finish line of the *build*; it's the start line of the *learning*.
