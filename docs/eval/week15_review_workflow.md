# Week 15 — Review / approval workflow

**Status:** ship

> Week 15 adds the firm accountability layer: engagements move
> through a review lifecycle (draft → in_review → changes_requested
> → approved → delivered) with role-gated transitions, structured
> reviewer feedback, and lock-on-approval. Segregation of duties is
> enforced by default (reviewer ≠ author). The trust stack is now
> "Argus verified the claims AND a partner reviewed and approved."

## Component check

| Component | Status | Evidence |
|---|---|---|
| State machine + schema + role gating | ✅ | Day 1; 11 tests (10 spec + 1 completeness) |
| Transition API + audit + lock-on-approval | ✅ | Day 2; 10 tests + Meridian smoke |
| Structured feedback + resolve-to-resubmit | ✅ | Day 3; 7 tests + multi-pointer smoke |
| Frontend — status / submit / panel / history | ✅ | Day 4; 5 component test files, 21 cases; tsc clean |
| **E2E — full multi-user review cycle** | ✅ | Day 5; 10/10 steps pass, 8/8 headline assertions |

## End-to-end demo (Meridian Advisory)

Driven via the W15/D2 transition service (no HTTP layer, no LLM
cost, ~11 seconds wall). All three Meridian users participated —
Marcus Thorne (consultant, author), Helena Voss (partner / admin
reviewer), Priya Shah (junior analyst, member, NOT assigned).

| # | Actor | Action | Result | Detail |
|---|---|---|---|---|
| 1 | Consultant | submit (assigns partner) | ✅ 200 | `draft → in_review` |
| 2 | Consultant | **approve own** | ✅ 403 | self-approval denied — `firms.allow_self_approval=false` |
| 3 | Analyst (member, not assigned) | approve | ✅ 403 | non-admin without explicit reviewer assignment |
| 4 | Partner | request_changes (1 major + 1 minor) | ✅ 200 | `in_review → changes_requested`; structured feedback persisted |
| 5 | Consultant | **resubmit early** | ✅ 409 | blocking pointer paths surfaced: `['synergy_estimate']` |
| 6 | Consultant | resolve major + resubmit | ✅ 200 | `changes_requested → in_review`; minor risks pointer left unresolved (advisory) |
| 7 | Partner | approve | ✅ 200 | `in_review → approved`; `approved_by != created_by_user_id` confirmed |
| 8 | Consultant | edit memo (auto-revert) | ✅ 200 | `approved → draft`; **14 artifacts flagged stale** |
| 9 | Consultant + Partner | resubmit + approve (round 2) | ✅ 200 | `draft → in_review → approved` |
| 10 | Consultant | mark delivered | ✅ 200 | `approved → delivered` |

### Headline assertions (8 / 8 PASS)

- ✅ `all_10_steps_pass`
- ✅ `self_approval_blocked` (step 2 — 403)
- ✅ `unauthorized_member_blocked` (step 3 — 403 for non-assigned member)
- ✅ `resubmit_gating_enforced` (step 5 — 409 with `blocking_pointer_paths=['synergy_estimate']`)
- ✅ `lock_on_approval_auto_revert` (step 8 — `approved → draft`)
- ✅ `review_records_sequence_complete` — observed action sequence matches expected exactly:
  `[submit_for_review, request_changes, resubmit, approve, auto_revert, submit_for_review, approve, mark_delivered]`
- ✅ `audit_covers_every_transition` — every `review_records` row has a matching `audit_events` row keyed by `review_record_id` (resolve_pointer audit row is an additional honest entry, not a missing one — `extra_audit_rows_count = 1`)
- ✅ `every_approval_reviewer_ne_author` — both approval rows in step 7 + step 9 have `actor_id == partner_id`, never the author

### Audit completeness

- `review_records`: 8 rows (one per state transition; step 5's blocked resubmit correctly leaves no row because the transition didn't commit)
- `audit_events`: 9 rows (8 transition audits + 1 `review.resolve_pointer` audit from step 6's pointer resolution)
- Every transition's audit payload carries the matching `review_record_id`, so the workspace timeline can join the two cleanly

## What works

- **The full multi-user accountability layer is live.** Three roles
  (admin partner, lead consultant, member analyst) interact through
  the same engagement and the system enforces exactly the rules the
  spec required: author can't approve their own work, members
  without explicit reviewer assignment can't approve, blocking
  pointers gate resubmission, approval locks the engagement.
- **Lock-on-approval is real, not a UI hint.** The W15/D2
  `auto_revert_if_locked` helper hooked into the section-deepening
  trigger + accept paths fires correctly when an edit hits an
  approved engagement. Step 8 of the cycle confirms it: the moment
  the consultant attempts an edit, the engagement reverts to draft,
  14 ready artifacts get tagged `metadata.stale_since_revert = true`
  (per the W13/D2 attachment-bundle awareness path), and a
  `review.auto_revert` audit row is appended.
- **Structured feedback discipline holds.** Section pointers MUST
  reference real payload paths (validated against the live
  `consulting_payload`); blank notes get dropped from the
  submitted payload at the API layer; minor pointers stay advisory
  while major/blocking ones gate resubmit. Step 5's 409 surfaces
  `blocking_pointer_paths=['synergy_estimate']` in the response
  body so the workspace UI can render the offending paths as
  clickable links to the affected sections.
- **Audit trail is complete.** 8/8 transitions logged to
  `audit_events` with the matching `review_record_id` in the
  payload, plus an additional `review.resolve_pointer` audit row
  for step 6 — workspace history can reconstruct the full
  back-and-forth including pointer resolutions.
- **Cost discipline.** $0.00 LLM cost across the entire cycle (the
  e2e uses seeded engagements + the transition service directly).
  Wall time: ~11 seconds for all 10 steps locally.
- **Frontend ready.** 6 review components shipped (status badge,
  submit modal, reviewer panel, changes-requested panel, history
  timeline, auto-revert dialog) with 21/21 component-test cases
  passing and `tsc` clean. The badge auto-fetches state in
  `WorkspaceTopBar`; other components are exported for the
  workspace shell to slot in.

## What's still open

- **Workspace shell wiring is partial.** Day 4 shipped the
  components + wired the status badge into `WorkspaceTopBar` —
  the submit modal, reviewer panel, changes-requested panel,
  history timeline, and auto-revert dialog are built and tested
  but not yet integrated into the main engagement workspace
  layout. That's a UX-polish task for Phase 4 Week 16/17 (the
  workspace already has a sidebar pattern from `ArtifactsRail` /
  `TeamPanel` that these slot into; small frontend work).
- **MemoEditor section anchors.** The W15/D4
  `ChangesRequestedPanel.onJumpToSection` callback is wired but
  the MemoEditor doesn't have addressable per-section anchors yet
  (it renders the whole memo as a prose tree). Scrolling to a
  flagged path will need section-anchor IDs threaded through the
  MemoRenderer in a follow-up.
- **Notifications.** Phase 4 Week 18 builds the notification
  layer; today the partner finds out their queue has work via
  the engagement-list badge change, not a push. Acceptable for
  W15 ship; W18 closes the gap.
- **Per-pointer threaded comments.** Phase 4 Week 16's inline
  commenting work supersedes W15's lightweight single-note
  pointers. Today's pointers are "fire-and-resolve"; W16 adds
  threaded discussion on each claim_id.
- **Reopen audit phrasing.** `ReviewAction.REOPEN` is admin-only
  and emits a clean audit row, but the workspace timeline
  doesn't yet highlight reopen events with the same urgency as
  request_changes events. UI polish only.

## Schema migrations

- `036_review_workflow.sql` — adds `sessions.review_state` (CHECK-
  constrained), denormalised columns, `review_records` table,
  `firms.allow_self_approval BOOLEAN DEFAULT FALSE`.
- `037_review_feedback.sql` — converts
  `review_records.feedback` TEXT → JSONB with idempotent
  backfill for legacy plain-text rows; GIN index on the pointer
  array. Down-migration is documented as lossy (pointers
  collapse to plain text).

Both migrations cycled cleanly up/down/up in Day 1 + Day 3.

## Tests

Across W15:

| Day | Tests | Pass |
|---|---|---|
| D1 — state machine | 11 (10 spec + 1 completeness) | 11/11 |
| D2 — transition API + auto-revert | 10 | 10/10 |
| D3 — structured feedback + resubmit gate | 7 | 7/7 |
| D4 — frontend components | 5 files / 21 cases | 21/21 |
| D5 — e2e cycle | 1 runner / 10 steps / 8 headline assertions | 10/10 steps + 8/8 headline |

Broader review + perms regression sweep: **89/89 pass**.

## Cost + timing

| Metric | Value |
|---|---|
| LLM cost (e2e) | $0.00 |
| Wall time (e2e) | ~11 s |
| review_records rows produced | 8 |
| audit_events rows produced | 9 |
| Artifacts flagged stale | 14 |
| Cycle iterations | 1 round of changes + 1 auto-revert round |

## Decision

- [x] **Ship Week 15.** Multi-user accountability layer is live end-to-end.
  The trust stack moves from "Argus verified the claims" to "Argus
  verified the claims AND a partner reviewed and approved."
- [ ] Iterate.

## Carry-forwards for Week 16

- **Inline threaded commenting on claim_ids** — supersedes the
  W15/D3 single-note pointers; the data model already has
  audit_events + the claim_id keying, so the schema work is
  small + the UI work is the substantive build.
- **MemoEditor section anchors** so
  `ChangesRequestedPanel.onJumpToSection` can scroll correctly.
- **Workspace shell wiring** for the remaining 5 W15/D4
  components (submit modal trigger on top bar, reviewer +
  changes panels in a right rail, history in a sidebar tab).

## Repro

```
python tools/seed_sample_workspace.py        # one-time, cached
python tools/run_week15_e2e.py               # ~11 s, $0.00
```

Re-running is idempotent: the runner resets the engagement to
draft + clears prior review_records + audit rows so the cycle
runs cleanly every time.
