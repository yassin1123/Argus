# Phase 4 — Close

**Status:** complete (tag: `phase-4-complete`)
**Closed:** 2026-05-24
**Branch:** `phase-4/week-19` — W19/D1, D2, D4, D5 committed.
W19/D3 (version-history UI) was deferred mid-flight to land the
Phase 4 integration demo (D4) instead; the backend (list + diff +
restore) is shipped + tested, the React surface is the first
carry-forward into Phase 5.

> Phase 4 set out to take the verified-deliverable suite Phase 3
> shipped and turn it into a team workflow — a partner reviewing
> a consultant's draft, a junior analyst contributing inline, a
> thread of mentions and notifications, complete provenance of how
> the deliverable evolved over the engagement. As of Day 5 the
> collaboration layer is complete and demonstrably interlocks:
> the Phase 4 demo runs 15 steps across all five workstreams on
> the seeded Meridian Kestrel engagement with 18/18 headline
> assertions passing.

## What Phase 4 delivered

- **Week 15 — Review / approval workflow** ✅
  Engagement lifecycle (`draft → in_review → changes_requested →
  approved → delivered`), role-gated transitions
  (reviewer-or-admin to approve, allow_self_approval firm flag for
  segregation-of-duties), `ReviewFeedback` schema with section
  pointers (`blocking | suggestion | nit`) + claim-id deltas,
  pointer resolution loop, lock-on-approval (post-approval edits
  auto-revert state with audit), submitter denormalised onto
  `sessions.submitted_by` for downstream notifications.
  [docs/eval/week15_review_workflow.md](week15_review_workflow.md)

- **Week 16 — Inline commenting** ✅
  Threaded comments anchored to **section / claim_id / artifact /
  text_range / artifact_element**, MemoRenderer-anchored
  (`data-claim-id` already in the W9 rendered DOM was the
  integration point — comments survive memo edits because they're
  attached to ids, not lines). `@`-mentions via email-prefix slugs.
  Resolve/unresolve. Orphan detection (claim retired by deepening
  → comment flagged with `attached to a retired claim`).
  Per-engagement comment overview surface.
  [docs/eval/week16_commenting.md](week16_commenting.md)

- **Week 17 — Assignment + collaboration state** ✅
  `engagement_memberships` with four roles (`lead | contributor |
  reviewer | observer`) + reviewer-alignment with W15
  `review_assigned_to`. Per-section ownership with work-status
  (`not_started | in_progress | needs_review | done`), coverage
  map with `ready_to_submit` advisory flag. Derived task
  aggregation (open changes-requested pointers + unresolved
  threads + own-section work) + explicit tasks. My-work view
  rolls every engagement an owner touches into one queue. Team
  panel, section ownership UI, activity feed.
  [docs/eval/week17_collaboration.md](week17_collaboration.md)

- **Week 18 — Notifications** ✅
  Nine notification types (`MENTION`, `COMMENT_REPLY`,
  `ENGAGEMENT_ASSIGNED`, `SECTION_ASSIGNED`, `SECTION_NEEDS_REVIEW`,
  `TASK_ASSIGNED`, `REVIEW_REQUESTED`, `CHANGES_REQUESTED`,
  `REVIEW_APPROVED`, `VERSION_RESTORED` — ten with W19's add).
  Dispatcher with per-type recipient resolution, hard
  actor-exclusion invariant ("never notify the actor for their
  own action"), `dedup_key` collapse so a single source event
  produces one notification per recipient even when multiple
  types qualify. In-app feed + capture/SMTP email adapter,
  per-user `notification_preferences` (in_app + email toggles
  per type). Notification center UI (bell, feed, deep-link
  navigation, preferences page).
  [docs/eval/week18_notifications.md](week18_notifications.md)

- **Week 19 — Version history + Phase 4 close** ✅
  `payload_versions` table (append-only, monotonic per
  `session_id`) with `change_type` enum (`initial | section_deepening
  | manual_edit | review_revert | restore`). W19/D1 wired three
  change points: `save_report → ensure_initial_version` (idempotent
  v1 seed), `accept_deepening → create_version(SECTION_DEEPENING)`,
  and the W15 auto-revert path → `create_version(REVIEW_REVERT)`.
  W19/D2 added `diff_versions` (per-section change + word-level
  segments via stdlib `difflib.SequenceMatcher`, matching the
  frontend W9 `DiffPanel` shape) + `restore_version` (7-step
  contract: permission gate → in-flight deepening check →
  approved-state confirmation → auto-revert if locked → persist
  snapshot → append RESTORE version → flag artifacts stale + audit
  + notify lead). Four endpoints (`list / diff / get / restore`)
  mounted at `/api/sessions/{id}/versions/...`.
  D4 shipped the Phase 4 integration demo.
  D5 is this close + tag.

## Phase 4 wedge demonstrated

The Phase 4 demo runner ([tools/run_phase4_demo.py](../../tools/run_phase4_demo.py))
drives a 15-step narrative across all five workstreams on the
seeded Meridian Kestrel engagement with three real users
(consultant lead, partner reviewer, analyst contributor). It
exercises:

  - W17 membership assignment + every trackable section owned
  - W9 + W19 deepening flow (synergy_estimate, valuation_range,
    financial_profile) bumping the version chain
  - W16 thread with cross-user `@`-mentions, replies, resolution
  - W15 submit → request_changes (blocking pointer) → resubmit
    → approve, with notifications fanning out at every transition
  - W19 history walked + v1 ↔ final diff rendered
  - Coverage `ready_to_submit` flag flips True when every owner
    marks their section done

The full 18/18 headline assertions pass on every run:
`all_steps_pass`, `final_review_state_approved`, version chain
coherent (4 versions, monotonic, initial + deepening change types,
review_state captured per snapshot), `coverage_ready_to_submit`,
mention notifications reached analyst + partner,
`partner_received_review_requested_x2` (submit + resubmit),
consultant received `changes_requested + review_approved`,
`actor_never_notified_for_own_action`, `dedup_held_no_multi_type
_per_source`, `audit_covers` `engagement./section./review./
comment.` classes, diff v1→final includes every deepened section.

A provenance narrative renders as the final output:

> This memo went through 4 version(s) over the engagement.
>   v1 (initial generation, review_state=draft, by the consultant…)
>   v2: the analyst deepened [synergy_estimate, …] (review_state=draft)
>   v3: the consultant deepened [valuation_range, …] (review_state=draft)
>   v4: the analyst deepened [financial_profile, …] (review_state=changes_requested)
> The final state is APPROVED at v4.

That's the Phase 4 wedge: a boutique firm can now run an
engagement as a team with full accountability — a consultant
drafts and owns sections, the team discusses inline with mentions
and notifications, a partner reviews and approves with segregation
of duties enforced, every change is versioned, and at the end the
firm can answer "how did we get to this recommendation, who said
what, and who signed off" from a single audit surface. The trust
stack is complete: Argus verified the claims (Phase 1), produced
six deliverables (Phase 3), and the team collaborated with
complete provenance plus partner sign-off (Phase 4).

Demo artifact:
[backend/eval_runs/phase4_demo/summary.json](../../backend/eval_runs/phase4_demo/summary.json).

## Carry-forwards into Phase 5

  - **W19/D3 version-history React surface** — backend (list +
    diff + restore + 4 endpoints) shipped + tested; the inline
    diff component + restore-with-confirm UX is the first
    Phase 5 carry. The W9 `DiffPanel` is already shape-compatible
    with `VersionDiff.section_changes[*].word_segments`.
  - **Production SMTP wiring** — capture adapter in dev; real
    pilots need an SMTP provider + DKIM/SPF set up + a
    bounce-handling path.
  - **Notification digest batching + real-time push** — today's
    notifications are per-event; a "you have 14 new mentions
    on Kestrel" digest + a WebSocket push are both pilot-tier
    polish items.
  - **Companies House TIFF/OCR** — open since Phase 1 (scanned
    historical filings still fall through to no-OCR placeholder
    text); the retrieval-polish work belongs to Phase 5 quality.
  - **Multi-instance cache invalidation** — single-node assumption
    holds today; a multi-node deploy needs the firm_modes cache,
    artifact registry, and notification preferences to invalidate
    cross-node. Pilots may land before that's needed; multi-tenant
    SaaS hosting can't.
  - **Text-range live re-anchoring** — text-range comments today
    pin to character offsets that drift when the section is
    deepened. The orphan detector flags this honestly; live
    re-anchoring under deepening is Phase 5.
  - **Element-level artifact commenting** — comments today anchor
    to `artifact` (the whole file). Element-level (per cell in
    Excel, per slide in PPTX) needs renderer-side hooks.
  - **WeasyPrint as a deploy dependency** — PDF artifact rendering
    needs pango/cairo/gdk-pixbuf; Docker builds it, Windows dev
    hosts don't. The Phase 4 demos all stayed away from PDF
    artifact paths so this didn't surface, but it's a real install
    story for the Phase 5 pilots.

## Phase 5 readiness assessment

Phase 5 = quality + observability + enterprise + pilots. Honest
readiness check:

  - **Verification spine** (Phase 1) — shipped, eval-gated. ✅
  - **Deliverable suite** (Phase 3) — six artifacts across both
    modes, regression 8/8. ✅
  - **Collaboration layer** (Phase 4) — review / discussion /
    ownership / notifications / version history, 18/18 demo
    assertions. ✅
  - **Sample workspace + multi-user fixtures** — Meridian
    Advisory with 3 users + 2 cached engagements seeded. ✅
  - **Audit trail** — comprehensive across `engagement.`,
    `section.`, `review.`, `comment.`, `task.`, `version.`,
    `section_deepening.` action classes. ✅

  - **Gaps that Phase 5 has to close before real-firm pilots:**
    - No production observability — no metrics, no request
      tracing, no cost dashboard (the per-job ceiling is enforced
      but there's no operator surface to watch it).
    - No SSO — the README claim is aspirational; dev auth today
      is local-only.
    - No data-retention / deletion controls.
    - No multi-instance deploy story (cache invalidation +
      session affinity).
    - NLI thresholds tuned on the eval set, not on real-firm
      evidence corpora.

  - Phase 5 starts on a complete *product* foundation — the core
    value (verified deliverables) and the team workflow
    (collaboration) both work end-to-end. What Phase 5 adds is
    the operational shell needed to put it in a partner's hands.

## Retro

**What went well in Phase 4.** The layers composed cleanly. The
dispatcher + recipient + preferences stack from W18 fanned out
every W15 review transition, every W16 mention, every W17
assignment, and every W19 restore without per-call-site special
casing — events go through one chokepoint and the dispatcher
resolves recipients per type. The W9 `MemoRenderer` having
`data-claim-id` in the DOM since Phase 2 meant W16's claim-anchor
comments were a single attribute query, not a re-architecture.
The W19 version-history schema slotted in as one append-only
table behind three existing change points (`save_report`,
`accept_deepening`, `auto-revert`) and a thin restore service —
no schema changes anywhere else in the platform. The Day 5
integration demo passing every assertion on the first end-to-end
run (after one bootstrap-loop fix for the missing initial v1
+ a coverage-distribution gap) is the strongest signal that the
five workstreams actually interlock rather than just coexist.

**What was tricky.** Recipient resolution + dedup was the most
subtle work in the phase — the obvious-looking rules (notify
mentioned users; notify the thread participants) compose into
seven edge cases (don't notify the actor for their own action;
collapse multi-type events on the same source; respect per-user
opt-outs without losing the audit row; resolve "the engagement
lead" from the *active* membership row, not whoever started the
session). The table-extension reconciliations were the other
sink: every new collaboration table (`section_assignments`,
`engagement_memberships`, `notifications`, `payload_versions`)
had to reconcile with the existing `audit_events` shape, the
W9 `section_deepening_runs` lifecycle, and the W15 `review_records`
denormalisation. Catching that the demo's `coverage` assertion
was failing because deepening *expands* the live payload shape
(adding `summary`, `key_reasons`, `risks`, `counterarguments`,
`next_steps` once they're flattened in the reports row) only
came out of running the demo end-to-end — the unit tests had
flat trackable sets that didn't surface the issue.

**What to carry into Phase 5.** Two disciplines:

  1. **Audit existing structure before building.** Every Phase 4
     workstream that went smoothly was the one that found an
     existing hook (W16 anchored to `data-claim-id`; W19 wired
     into the three existing change points). The ones that were
     tricky were the ones that introduced parallel structure
     before checking whether the platform already had a spot for
     it (early W17 spec had a separate `engagement_users` table
     that turned out to overlap with `engagement_memberships`).
     Phase 5's enterprise + observability work has higher
     structural-overlap risk (SSO touches `users`; observability
     touches every request path); the rule "grep the codebase
     before specifying a new table" is now permanent.

  2. **The cost-capped run rule.** Every demo + e2e in Phase 4
     stayed on the capture email adapter + the no-LLM
     `_stage_and_accept_deepening` shortcut. That kept the
     full-stack demo at $0 and made it CI-cheap. Phase 5 pilots
     are the first time real LLM cost lands on real engagements;
     the per-run cap + cost analytics surface need to be the
     first observability work, not the last.

