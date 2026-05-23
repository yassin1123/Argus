# Week 17 — Assignment + collaboration state

**Status:** ship

> Week 17 makes engagement collaboration explicit: engagement
> membership (lead / contributor / reviewer / observer), per-section
> ownership + work-status, and a unified "my work" view that derives
> tasks from W15 change requests, W16 comments/mentions, and W17
> section assignments. Reviewer role aligns with the W15 review gate.
> Section work-status is distinct from the engagement review-state.
> The three collaboration layers now interlock: formal review (W15),
> discussion (W16), and ownership/tasks (W17).

## Component check

| Component | Status | Evidence |
|---|---|---|
| Engagement membership + roles (W17/D1) | ✅ | 9 tests |
| Section ownership + work-status + coverage (W17/D2) | ✅ | 9 tests |
| Derived task aggregation + explicit tasks + my-work (W17/D3) | ✅ | 9 tests |
| Frontend — team panel / ownership overlay / coverage / my-work / activity feed (W17/D4) | ✅ | 21 cases across 5 component test files; tsc clean |
| **E2E — full collaboration flow** | ✅ | 11/11 steps + 14/14 headline assertions |

## End-to-end demo (Meridian Advisory)

Driven via the W17 + W15 + W16 service layers against the seeded
Meridian Kestrel engagement (no HTTP layer, no LLM cost; one
section deepening is NOT needed because we never re-run W9 in this
flow — coverage / status / mention paths don't touch the deepener).
All three Meridian users participate: Marcus Thorne (consultant,
auto-assigned lead on session creation), Helena Voss (partner /
reviewer), Priya Shah (junior analyst, contributor).

| # | Actor | Action | Result |
|---|---|---|---|
| 1 | Lead | Assign analyst as contributor | ✅ `contributor` role persisted |
| 2 | Lead | Assign partner as **reviewer** | ✅ `sessions.review_assigned_to` aligned with partner_id (W15 hook fired) |
| 3 | Lead | Assign `synergy_estimate` → analyst, `valuation_range` → self | ✅ both assignments persisted |
| 4 | System | Coverage map snapshot | ✅ 2 assigned, 9 unassigned, `ready_to_submit=False` |
| 5 | Analyst | `synergy_estimate`: not_started → in_progress → needs_review | ✅ status transitions + `section.needs_review` event emitted |
| 6 | Analyst | Comment on `valuation_range` mentioning `@marcus.thorne` | ✅ comment row + mention resolved to lead's user_id |
| 7 | Lead | `/api/me/work` aggregates | ✅ valuation_range as `section_incomplete` (medium) + mention as `mention` (medium) |
| 8 | Lead → Partner | Submit for review → partner requests changes (blocking on synergy_estimate) | ✅ `draft → in_review → changes_requested` |
| 9 | Analyst | `/api/me/work` after change request | ✅ new `change_request` derived task on synergy_estimate, priority `high` |
| 10 | Lead + Partner | Address change request → mark all sections done → resolve pointer → resubmit → approve | ✅ `ready_to_submit=True` surfaced (advisory); `changes_requested → in_review → approved` |
| 11 | System | Final assertions | ✅ engagement `approved`; 3 members active; coverage covers every trackable section in DONE |

### Headline assertions (14 / 14 PASS)

- ✅ `exactly_one_lead`
- ✅ `lead_is_consultant`
- ✅ `all_three_users_on_engagement`
- ✅ `reviewer_role_aligned_with_review_assigned_to` — W17/D1 hook
  set `sessions.review_assigned_to` when the partner was assigned
  reviewer (no W15 cycle in flight)
- ✅ `section_status_transitions_landed_done`
- ✅ `coverage_map_accurate_initial`
- ✅ `lead_my_work_includes_owned_section_and_mention`
- ✅ `analyst_my_work_includes_change_request`
- ✅ `cross_ref_change_request_section_correct` — the W15 review
  feedback's `section_pointer.section_path = "synergy_estimate"`
  joined cleanly through `section_assignments.assigned_to = analyst`
  to produce a high-priority derived task
- ✅ `cross_ref_mention_present` — W16
  `comments.mentioned_user_ids @> [lead]` produced a derived
  `mention` task for the lead via the W16/D4 GIN index path
- ✅ `audit_covers_all_collaboration_classes` — every action
  prefix (engagement / section / review / comment) present in
  `audit_events`
- ✅ `section_status_distinct_from_review_state` — confirmed
  by step 5: analyst marked `synergy_estimate=needs_review` while
  the engagement was still in `draft`
- ✅ `ready_to_submit_surfaced_before_resubmit` — coverage map's
  advisory flag flipped True after the cleanup pass; the system
  did NOT auto-submit
- ✅ `final_review_state_approved`

### Audit completeness

- **44 audit rows** on the engagement spanning every collaboration
  class. Counts by action class:
  - `engagement.member_assigned` × 2 (analyst + partner)
  - `section.assigned` × 11 (synergy + valuation + 9 cleanup-pass)
  - `section.status_changed` × 13 (synergy x2, valuation x1, 9 cleanup, analyst+lead transitions)
  - `section.needs_review` × 1 (analyst's intermediate state in step 5)
  - `review.submit_for_review` / `request_changes` / `resolve_pointer` / `resubmit` / `approve` — full W15 cycle
  - `comment.created` + `comment.mention` × 2 — emitted via the
    W16/D2 audit shape (the e2e runs the service layer directly,
    so we replicate the API-layer audit that the HTTP request
    would have written)

## What works

- **The three collaboration layers interlock.** A change request
  on a section the analyst owns (W15) immediately appears in
  their `/api/me/work` as a high-priority derived task (W17). A
  @-mention on a comment (W16) appears as a medium derived task
  in the mentioned user's plate. Neither cross-reference requires
  any new schema — both are JOINs through `section_assignments` +
  `mentioned_user_ids @>` against existing tables.
- **Reviewer role alignment with W15 is live.** Assigning role
  `reviewer` sets `sessions.review_assigned_to` to that user
  unless the engagement is mid-cycle with a different reviewer
  (safety branch in `_maybe_align_review_assignment`). The W15
  authorisation gate then lets the assigned reviewer approve
  without admin role. No drift between the two states is
  possible: the assignment write owns the alignment.
- **Section status is granular and distinct.** A section can be
  `done` while the engagement is `draft`; an engagement can be
  `approved` while individual sections were never assigned. The
  two state machines never share a column and the
  ``section_status_distinct_from_engagement_review_state`` test
  pins the invariant explicitly.
- **One-lead invariant holds end-to-end.** The bootstrap auto-
  assigned the consultant as lead at session creation; the W17
  service rejects second-lead assignment with 409 (user
  decision — demote-first is intentional manual operation, not
  auto-magic).
- **My-work dedup works.** A mention on an owned section
  produces a single `mention` task (the higher-priority winner),
  not a duplicate `mention` + `comment_on_owned_section` pair.
  Verified in W17/D3's `test_derived_tasks_deduplicated`.
- **Coverage map's advisory `ready_to_submit` is honest.** It
  fires True only when every trackable section in the live
  payload is both assigned AND done. The W17/D2 hard rule
  ("don't auto-submit") keeps the partner in control: the flag
  is surfaced, the action stays manual.
- **Frontend slot doesn't collide with W16.** Section header
  carries owner avatar + status pill LEFT of the comment
  affordance; both are smaller / lower-priority than the comment
  badge so the visual hierarchy stays right. The combined
  `SectionWrapper` + `MemoRenderer` plumbing is opt-in (omit
  the prop and the legacy memo render path is unchanged).
- **Cost discipline.** $0.00 LLM cost across the entire cycle
  (the e2e drives the W15 / W16 / W17 services directly; no
  W9 deepening is needed in this flow). Wall time: **~15 s**
  for all 11 steps locally.

## What's still open

- **Notification delivery for assignments / status changes /
  mentions — W18.** Today the system EMITS the events
  (`section.needs_review`, `comment.mention`, `engagement.member_assigned`)
  via audit_events. W18 picks them up and routes to in-app +
  email. The pull-side stop-gap is already live — users land
  on `/api/me/work` and see their plate, but they have to look
  at the dashboard to find out a thread is waiting.
- **Drag-and-drop section reassignment — Phase 5 polish.** Click
  to pick is the W17/D4 hard rule; drag-and-drop reassignment
  is purely an interaction-quality improvement, not a missing
  capability.
- **Cross-engagement my-work as a true home dashboard — partially
  built.** The API (`/api/me/work`) + component
  (`MyWorkDashboard`) exist and are tested; full home-page
  integration (replacing or augmenting `EngagementsHome`) is
  W19 / Phase 5 work. Today a host can drop the component into
  any page with `<MyWorkDashboard currentUserId={uid} />`.
- **Real-time activity feed — Phase 5.** The `ActivityFeed`
  component refreshes on mount + manual button. WebSocket
  / polling-based push is intentionally deferred.
- **Section assignments need a "depends on" surface for sequenced
  work** (e.g. "valuation needs the synergy_estimate to be done
  first"). Not in the W17 scope and the W17/D3 hard rule says
  "don't build a full PM system"; we'll see whether real users
  ask for it.

## Schema migrations

- `040_engagement_member_roles.sql` (W17/D1) — extends the W2-era
  `engagement_memberships` table with the W17 role vocabulary
  (`lead / contributor / reviewer / observer`), adds
  `removed_at TIMESTAMPTZ` for soft-remove, and backfills leads
  from `sessions.created_by_user_id`. Partial active-only indexes
  keep the soft-remove query path tight.
- `041_section_assignments.sql` (W17/D2) — new
  `section_assignments` table with one row per
  (session_id, section_path), CHECK-constrained status enum,
  UNIQUE constraint enforcing one owner at a time. UPSERT
  preserves status on re-assign.
- `042_engagement_tasks.sql` (W17/D3) — lightweight explicit-task
  table (title + assignee + section_path + done). No subtasks,
  no dependencies, no due dates — per hard rule, this is the
  ad-hoc escape hatch, not a full PM system. Partial index on
  open tasks per assignee.

All three cycle cleanly up/down/up; the W17/D1 migration also
includes a backfill that promotes every existing session's creator
to lead (idempotent — ON CONFLICT updates the role).

## Tests

| Day | Tests | Pass |
|---|---|---|
| D1 — membership service | 9 | 9/9 |
| D2 — section ownership + work-status + coverage | 9 | 9/9 |
| D3 — derived tasks + explicit tasks + my-work | 9 | 9/9 |
| D4 — frontend (TeamPanel / SectionOwnershipOverlay / CoverageIndicator / MyWorkDashboard / ActivityFeed) | 5 files / 21 cases | 21/21 |
| D5 — e2e cycle | 1 runner / 11 steps / 14 headline assertions | 11/11 + 14/14 |

Broader backend regression sweep: **593 passed, 6 skipped** (the
6 skipped are pre-existing env-dependent NLI / multi-provider
tests, unrelated to W17). Full frontend sweep: **127 passed across
32 files**. `tsc --noEmit` clean.

## Cost + timing

| Metric | Value |
|---|---|
| LLM cost (e2e) | $0.00 (W15/W16/W17 service layer only; no W9 deepening) |
| Wall time (e2e) | ~15 s |
| audit_events rows produced | 44 (every collaboration class covered) |
| Members provisioned | 3 (lead + reviewer + contributor) |
| Sections covered | 11 / 11 (cleanup pass to surface `ready_to_submit`) |
| Derived tasks aggregated (lead's view at step 7) | 2 (1 owned-section + 1 mention) |
| Derived tasks aggregated (analyst's view at step 9) | ≥ 1 high-priority `change_request` |

## Decision

- [x] **Ship Week 17.** The three collaboration layers (formal
  review / discussion / ownership-tasks) interlock cleanly with
  no drift between reviewer role and W15 `review_assigned_to`,
  no double-counting in derived tasks, no leakage across users
  or firms, and full audit coverage. Section status is distinct
  from engagement review state by construction.
- [ ] Iterate.

## Carry-forwards for Week 18

- **Notification delivery.** Every signal the W18 layer needs is
  already emitted as an audit event today. The W18 worker
  consumes `comment.mention`, `section.needs_review`,
  `engagement.member_assigned`, `review.requested_changes`, and
  routes via in-app + email. No new schema; the W17/D3
  audit-event payload shape is the contract.
- **Last-read pointers per user.** The W16/D4 MyMentions view
  uses an `unreadSince` timestamp the host supplies (today this
  is localStorage). W18 will replace with a real
  per-user-per-resource last-read row so unread state is durable
  across devices.
- **Cross-engagement dashboard.** W17/D3's `/api/me/work` API +
  W17/D4's `MyWorkDashboard` component are ready to slot into
  the home page; this is mostly nav integration, not new
  feature work.

## Repro

```
python tools/seed_sample_workspace.py        # one-time, cached
python tools/run_week17_e2e.py               # ~15 s, $0.00
```

Re-running is idempotent: bootstrap resets the engagement to
draft, deletes prior comments / section_assignments / explicit
tasks / collaboration audit rows, and reinstates the consultant
as the sole lead so the W17/D1 invariants hold across runs.

## Files of record

- `backend/db/migrations/040_engagement_member_roles.sql` — extend
  engagement_memberships with W17 vocabulary + soft-remove
- `backend/db/migrations/041_section_assignments.sql` — section
  ownership + work-status table
- `backend/db/migrations/042_engagement_tasks.sql` — explicit
  task table
- `backend/core/collaboration/` — six modules:
  `roles.py`, `membership.py`, `section_status.py`,
  `section_assignments.py`, `coverage.py`, `tasks.py`,
  `explicit_tasks.py`, `my_work.py`
- `backend/api/collaboration.py` — 14 endpoints (W17/D3
  `/me/work` + `/sessions/{id}/work` + tasks; W17/D4 members CRUD
  + section assign/status/coverage)
- `frontend/lib/api/collaboration.ts` — typed client + display labels
- `frontend/components/Collaboration/` — 6 components + 5 tests
- `tools/run_week17_e2e.py` + `backend/eval_runs/week17_e2e/summary.json`

## Hard-rule audit

- ❌ Reviewer role and W15 `review_assigned_to` drift? **No.**
  Assertion 4 — alignment fires on assign_member(role=reviewer)
  unless a different reviewer is mid-cycle.
- ❌ Derived tasks double-count or leak across users/firms?
  **No.** Mention-on-owned-section dedup verified in W17/D3
  unit tests; `/api/me/work` is self-only; cross-user
  `/api/sessions/{id}/work?user_id=` is lead/admin-only with a
  TestClient assertion pinning it.
- ❌ Section status and review_state conflated? **No.**
  Assertion 12 — confirmed by step 5's needs_review while
  engagement still draft.
- ❌ Collaboration actions miss audit? **No.** Assertion 11 —
  every action prefix present; 44 rows total.
- ❌ LLM cost? **$0.00.** Service-layer drive, no W9 deepening
  in the flow.
