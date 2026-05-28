# Pilot operator runbook

The operator's manual for running the Blackmont pilot. This is a
playbook, not a vibe: every check has a concrete threshold and every
threshold has a concrete action.

**Operator:** Yassin. **Pilot firm:** Blackmont Consulting.
**Posture (W24/D1):** GREEN — full "verified" posture; the verifier is
conservative (zero false positives on real claims, but under-credits),
so expect more human-review flags than strictly necessary.

---

## 0. Before handover — the smoke check

Run **before** the pilot firm touches the system, and after any deploy:

```
python tools/pilot_smoke_check.py
```

**Do not hand over unless it returns all-green.** A RED on `config`
means a missing key / degraded verifier — fix it; never run the pilot
in a degraded mode. The deep variant (`--run-engagement`) drives a live
engagement (~$2-4) and is the Day-5 dress-rehearsal gate.

---

## 1. Daily checks (5 minutes)

Open the admin dashboard (`/admin` → observability), scoped to
Blackmont. Walk these in order. Each row: **what to look at →
green band → action threshold.**

| Signal | Where | Green | Act when |
|--------|-------|-------|----------|
| System health (success rate) | dashboard `volume.success_rate_pct` | ≥ 95% | **< 90%** → open `recent_failures`, triage top failure |
| In-flight stuck | `volume.in_flight` | 0–2 transient | **any engagement in-flight > 30 min** → check the trace, likely a stuck stage |
| Errors | `recent_failures` | empty | **any failure** → click into the W20 trace, find `failed_stage` |
| Cost burn | `cost_alerts` panel | empty | **any `warn` (≥75%)** → tell the firm; **`critical` (≥100%)** → soft-stop is live, raise the budget if legit |
| Verification distribution | `verification` panel | flags present but not 100% | **> 60% of claims flagged** → see "verifier flags everything" below |
| Claim feedback | `pilot_health.claim_feedback` | `correct` ≥ 70% | **`wrong_supported` > 5%** → escalate (false positives are the dangerous class) |
| Artifact ratings | `pilot_health.artifact_ratings` | avg ≥ 3.5 | **avg < 3.0** → read the comments, find the weak deliverable type |
| Edit rate | `pilot_health.edit_rate` | avg ≤ 40% | **avg > 60%** → the drafts aren't usable; flag for product work |

If every row is green, you're done for the day. Log nothing; act on nothing.

---

## 2. Incident response

Concrete scenarios and the exact first moves.

### Engagement fails mid-run
1. Dashboard → `recent_failures` → note `session_id`, `failed_stage`,
   cost burned.
2. Open the W20 trace for that session (`/api/sessions/{id}/trace`).
3. If `failed_stage` is an LLM call → check `config` smoke (key/quota);
   re-run the engagement.
4. If it's the verifier/DeBERTa stage → check the NLI worker is up
   (`docker compose ps`); restart if down.
5. If it recurs on the same input → take that engagement offline
   (tell the consultant "we're looking at it"), reproduce locally,
   push a fix (§4).

### Verifier flags everything (> 60% flagged)
This is the conservative-verifier behavior (W24/D1), not necessarily a
bug. Steps:
1. Pull the claim-feedback distribution — if consultants are marking the
   flags `wrong_flagged`, the verifier is over-cautious on this firm's
   content (expected; reassure the firm those are safe-side flags).
2. If they're marking `correct` (i.e. the flags are right) → the firm's
   evidence is genuinely thin; coach on uploading better library content.
3. Only escalate to verifier work if `wrong_supported` appears — that's
   the dangerous direction and contradicts the GREEN gate.

### A firm member can't log in
1. Confirm the user exists + is a member:
   `python tools/pilot_setup.py add-user --firm blackmont-consulting
   --email <them> --role firm_member --name "<Name>"` (idempotent —
   re-running fixes a missing membership).
2. If the account exists, issue a password reset via the W18 email flow.
3. If email isn't delivering, check `ARGUS_EMAIL_ADAPTER` (pilot uses
   `capture` or `smtp`; smtp needs `SMTP_*` set).

### An artifact didn't render
1. Dashboard → the engagement → artifact status. A `failed` artifact has
   a `failure_reason`.
2. Re-generate it (the export is idempotent).
3. If a specific type fails repeatedly (e.g. `excel_model`) → reproduce
   locally, it's usually a payload-shape edge case; push a fix (§4).

---

## 3. Weekly cadence

- **Monday:** glance at the week's check-in trend
  (`pilot_health.checkin_trend`). Last week's `would_keep_using` = the
  pulse.
- **Wednesday:** prompt the firm_admin to fill the in-app check-in
  (Day-3 form, `/pilot/checkin`). 7 questions, 2 minutes.
- **Friday:** send the firm a one-paragraph operator summary:
  engagements run, average rating, anything you fixed, anything you need
  from them (e.g. more library content). Pull the numbers from the pilot
  dashboard — don't editorialize the verifier's conservatism away.
- **Friday:** metrics review for yourself — edit rate trend, rating
  trend, claim-feedback trend. These three decide whether the pilot is
  working (§5).

---

## 4. Escalation paths

- **Hotfix (engagement-breaking bug):** fix on a branch off `main`, run
  `pytest backend -q` + `python tools/pilot_smoke_check.py`, merge to
  `main`, deploy. Never deploy a red smoke check.
- **Non-urgent product issue (high edit rate, weak deliverable):** log
  it; it's Phase 6 input, not a pilot hotfix. Don't churn the firm's
  running engagements for it.
- **Take an engagement offline:** if an engagement is producing wrong
  output a consultant might ship, tell them to hold, mark it, and
  reproduce. A wrong deliverable in front of *their* client is the one
  unrecoverable failure — bias toward pulling it.
- **Budget overage:** if a firm hits `critical` (100%) legitimately,
  raise `firms.monthly_budget_usd` (the soft-stop only blocks NEW
  engagements; in-flight ones finish). If it's runaway/abuse, leave the
  stop and investigate the rate-limit metrics.

---

## 5. Pilot success criteria (quantitative)

"This pilot is working" means, sustained over the pilot window:

| Metric | Target | Source |
|--------|--------|--------|
| Verification accuracy (consultant `correct` rate) | **≥ 80%** | `pilot_health.claim_feedback.pct.correct` |
| False-positive rate (`wrong_supported`) | **≤ 5%** | `pilot_health.claim_feedback.pct.wrong_supported` |
| Edit rate (kept vs rewritten) | **≤ 40%** avg | `pilot_health.edit_rate.average_edit_pct` |
| Artifact ratings | **≥ 3.5 / 5** avg | `pilot_health.artifact_ratings.average_rating` |
| Willingness to continue | **"yes"** on the weekly check-in | `pilot_health.checkin_trend[].responses.would_keep_using` |

Edit rate is the killer signal: if consultants rewrite > 60% of every
draft, the system isn't saving them time regardless of what the
verification numbers say. Two consecutive weeks above 60% edit rate is a
"pause and fix the drafts" trigger, not a "keep pushing" one.
