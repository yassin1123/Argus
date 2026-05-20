# Phase 4 — Scope (Weeks 15–19)

**Status:** planning — Phase 3 closed 2026-05-20 (`phase-3-complete` tag).
**Phase 4 entry condition:** the six-artifact deliverable suite works
end-to-end across modes. Met.

> Phase 4 is the human-in-the-loop / collaboration overhaul. Phase 3
> turned the verified-claim base into a deliverable suite for a
> *single* consultant operating an engagement. Phase 4 turns that
> single-operator surface into a team workflow — consultant drafts,
> partner reviews, junior analyst contributes, comments thread on
> claim_ids, version history is legible, notifications keep the team
> in sync. The underlying data model (multi-user firms, engagement
> memberships, audit log, section deepening) is in place from earlier
> phases; Phase 4 is the workflow layer on top.

## Five workstreams

### Week 15 — Review / approval workflow

The core flow. Consultant marks an engagement as ready for review;
partner gets the engagement in their queue; partner approves,
requests changes, or sends back to draft with comments. Built on
existing `engagement_memberships` (`lead` / `member`) + a new
`engagement_review_cycles` table.

  - **Schema:** `engagement_review_cycles` (engagement_id,
    submitted_by, submitted_at, reviewer_id, status, decision,
    decision_at, decision_notes). `engagement.review_status` derived
    column.
  - **States:** `draft → in_review → approved` (terminal) /
    `changes_requested → draft` (loop). One active cycle per
    engagement at a time.
  - **API:** `POST /api/sessions/{id}/submit_for_review`;
    `POST /api/sessions/{id}/review_decision` (lead + admin only).
  - **UI:** "Submit for review" button on the workspace top bar;
    partner queue surface on the engagement list page (filter:
    `assigned-to-me-for-review`); decision panel with
    approve / request-changes / send-back actions.
  - **Audit:** every state transition writes an `audit_events`
    row with the actor + decision_notes.

### Week 16 — Inline commenting on claims

Comments thread on **claim_ids**, not on text spans. A claim's
text can evolve through section-deepening + writer revisions, but
its claim_id is stable — so comments survive memo edits and stay
attached to the underlying assertion.

  - **Schema:** `claim_comments` (claim_id, engagement_id,
    author_id, body, parent_comment_id, created_at, resolved_at,
    resolved_by). Threaded via parent_comment_id.
  - **UI:** comment-pip badge on every claim chip in the 1-pager,
    deck, memo (the existing `data-claim-id` attribute is the
    integration point); side panel surface for open threads;
    "@mention" support (renders as a notification trigger in
    Week 18).
  - **Visibility:** any firm member with engagement membership can
    read + author; resolved threads collapse but stay viewable.
  - **Edge case:** when a section-deepening run replaces a claim
    with a fresh claim_id, the prior comments are flagged as
    "attached to a retired claim — review whether they apply to
    the replacement".

### Week 17 — Engagement collaboration state surface

The "who's working on what" view. Lifts the existing per-engagement
membership + the new review-cycle state + the section-deepening
in-flight runs into one workspace-level dashboard.

  - **No new schema** — this is a UI + read-only API workstream.
  - **Surface:** an engagement dashboard panel showing: current
    review status, who's the lead, who else is on the team,
    open comment count, in-flight deepening count, last
    artifact-generation timestamp per format.
  - **Firm-level view:** roll-up across every engagement for a
    partner who needs to know what's in their queue + what their
    team is working on.

### Week 18 — Notifications

Inline + email notifications for the events that matter to the
workflow.

  - **Schema:** `notifications` (recipient_user_id,
    notification_kind, engagement_id, claim_id, actor_id, payload,
    read_at, dismissed_at). Kinds: `review_requested`,
    `changes_requested`, `approved`, `comment_mention`,
    `comment_reply`, `deepening_completed`.
  - **Delivery:** in-app first (notifications dropdown on the
    workspace top bar); email opt-in second (uses the W13 cover
    email exporter's HTML template — text-only, mail-client-safe).
  - **Quiet hours + digest:** Phase 4 starts with per-event email;
    Phase 5 layers digest preferences if customers ask.

### Week 19 — Version history UI + Phase 4 close

Surfaces the existing section-deepening + the future review-cycle
revisions as a coherent engagement timeline.

  - **No new schema** — `section_deepening_runs` and
    `engagement_review_cycles` already carry the source data.
  - **UI:** chronological feed on the engagement page: every
    deepening run (with accept / reject), every review cycle
    (submit, decision, notes), every artifact regeneration. Filter
    by event kind.
  - **Close:** Phase 4 regression test mirroring W14/D4 — generate
    a full engagement, submit for review, partner requests
    changes with comments, consultant edits + resubmits, partner
    approves, version-history UI reflects the loop. Asserts the
    end-to-end workflow.

## Cross-cutting concerns

### Close the W14/D1 schema-enforcement carry-forward early

The growth Porter's content gap (writer emits `frameworks: null`)
is on the Phase 4 boundary. Tactically: land the
`GrowthStrategyReportPayload` Pydantic subclass in Week 15 so the
review workflow has live LLM-generated Porter's to gate on. Plan
is documented in
[../eval/week8_frameworks.md](../eval/week8_frameworks.md) under
"W14/D1 update".

### Don't bloat the writer schema for the workflow

Comments + review-cycle state live in their own tables. Writer
payloads stay focused on the deliverable; collaboration state is
orthogonal. Resist the temptation to fold `comments_count` /
`review_status` into the writer payload.

### Keep cost discipline from Phase 3

W14/D1 demonstrated the value of static diagnosis ($0 LLM cost to
confirm a hypothesis via stored telemetry); W14/D3 demonstrated
the value of cached fixtures for demo / test re-runs. Phase 4
inherits both: every workflow test should run against the cached
Meridian workspace seed, not a fresh LLM pipeline.

## What Phase 4 is *not*

  - **Not v1.0.** v1.0 is Phase 5 — real-firm pilots with real
    deliverables shipped to real client partners. Phase 4 ships the
    collaboration shape; Phase 5 validates it under load.
  - **Not real-time co-editing.** Comments + review cycles are
    async; live multi-cursor editing on the memo would be Phase 5+
    if customers ask. The W14/D3 sample workspace is the
    multi-user fixture, not a co-editing prototype.
  - **Not external collaborator support.** Phase 4 stays inside the
    firm — partner reviews consultant; firm-scoped permissions
    hold. External-reviewer flows (client signs the approval) are
    deferred.
  - **Not a notification preferences engine.** Per-event email
    delivery only in Phase 4; digest + quiet hours later.

## Phase 4 entry checklist (from W14/D5 close doc)

- [x] Multi-user firms schema (Week 5)
- [x] Firm-membership + engagement-membership roles
- [x] Audit log (`audit_events`)
- [x] Sample workspace fixture with multiple users + engagements
- [x] Section deepening accept / reject + history (Week 9)
- [x] Six-artifact deliverable suite live across modes (Phase 3
      regression passes)

All entry conditions met. Phase 4 opens on a verified foundation.

## Carry-forward into Phase 5

  - **Real-firm pilots** (the v1.0 gate).
  - **Companies House TIFF / OCR.**
  - **Multi-instance cache invalidation.**
  - **Multi-language template support.**
  - **Bloomberg / FactSet / Refinitiv connectors for finance verticals.**
  - **Mobile review experience.**
  - **Public sample workspace** for prospective firms (the W14/D3
    Meridian fixture is the seed for this).

Phase 5 = production validation + enterprise integrations.
