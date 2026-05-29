# Live-pilot issue log

Every real-world problem during the pilot is a finding — log it here the
moment it surfaces, however small. This is the pilot's raw learning; an
unlogged issue is a lesson lost.

**How to use:** when something breaks or looks off during the live pilot,
add a row immediately. Diagnose via the W20 trace (`/api/sessions/{id}/trace`)
and the W25/D2 live-pilot view (`/api/admin/observability/live-pilot`).
Decide **fix-now** (engagement-breaking; hotfix per the runbook §4) vs
**note-for-retro** (quality/UX; Phase 6 input). Don't touch the firm's
data or engagements without their say-so.

## Severity

- **P0** — firm is blocked / wrong output could reach their client. Fix now.
- **P1** — degraded but workable; fix this week.
- **P2** — papercut / note for the retro.

## Log

| Date | Sev | What happened | Where (trace/stage) | Root cause | Action | Status |
|------|-----|---------------|---------------------|------------|--------|--------|
| _(none yet — first real engagement pending)_ | | | | | | |

<!--
Example row format:
| 2026-05-30 | P1 | M&A engagement came back 80% insufficient | trace <id>, verifier stage | firm's library was image-only PDFs (no extractable text) | documented workaround: re-upload text PDFs; W14 OCR is a Phase-6 item | open |
-->

## Standing watch-items (from W24/D1 + dress rehearsal)

These aren't bugs — they're known characteristics to watch for in live data:

- **Conservative verifier (W24/D1):** expect more "needs review" flags than
  strictly necessary (recall-on-supported ~27% on the real-claim set). If
  consultants mark those `wrong_flagged`, that's expected over-caution, not
  a defect. Only `wrong_supported` (a missed false positive) is an escalation.
- **Anomalous verification distribution:** the live-pilot view flags when
  the firm's content produces an abnormal mix (e.g. ≥70% insufficient) — a
  signal the firm's library may be shaped differently than our synthetic
  content (image-only PDFs, thin evidence, etc.), not a verifier fault.
- **Edit rate is unmeasured until live:** the true rewrite rate only appears
  once real consultants edit real drafts (the dress rehearsal approved
  without edits). Watch it against the runbook bar (≤40%).
