# Week 16 — Inline commenting / threaded discussion

**Status:** ship

> Week 16 adds threaded discussion anchored to sections, claims,
> and artifacts. @-mentions resolve to firm members via a
> canonical email-prefix slug (delivery wired in W18). Threads
> resolve / unresolve at the root. text_range anchors flag
> orphaned when the underlying text changes (via the W9 section
> deepening path); section / claim / artifact anchors survive.
> Integrates with the W15 review workflow: the review GET
> response now carries an advisory `comments: {unresolved, total}`
> block so a reviewer sees open-thread count before approving,
> but approval is **not** gated on it.

## Component check

| Component | Status | Evidence |
|---|---|---|
| Comment schema + anchoring + CRUD | ✅ | Day 1; 10 service tests |
| Comment API + threading + mention parsing + review integration | ✅ | Day 2; 11 API tests |
| MemoRenderer comment UI (section + claim) + thread panel + mentions | ✅ | Day 3; 5 component test files, 15 cases |
| Artifact comments + engagement overview + my-mentions view | ✅ | Day 4; 5 backend + 8 frontend tests |
| **E2E — multi-user discussion + review integration** | ✅ | Day 5; 10/10 steps, 11/11 headline assertions |

## End-to-end demo (Meridian Advisory)

Driven via the W16/D1+D2 service layer against the seeded
Meridian Kestrel engagement (no HTTP layer, no LLM cost — the
"section deepening" step is a deterministic in-place rewrite,
since the orphan detector cares about the OBSERVABLE state
change, not the LLM that produced it). All three Meridian users
participate — Marcus Thorne (consultant, author), Helena Voss
(partner / admin), Priya Shah (junior analyst, member).

| # | Actor | Action | Result |
|---|---|---|---|
| 1 | Consultant | section comment on `synergy_estimate` mentioning `@helena.voss` + a bogus `@ghost.user` slug | ✅ root created; partner ID stored; non-member slug silently dropped |
| 2 | Consultant | text_range comment quoting `PRE_DEEPEN_MARKER_W16D5 …` (used for step 9's orphan check) | ✅ stored with `start/end/quoted_text` |
| 3 | Partner | reply mentioning `@priya.shah` | ✅ reply inherits root anchor; analyst ID stored |
| 4 | Analyst | reply on the same thread | ✅ second reply nested under root |
| 5 | Consultant | claim comment on `claim_revenue_1` (real claim from seed payload) | ✅ anchored to claim_id |
| 6 | Consultant | artifact comment on the deck | ✅ anchored to `artifact_id` |
| 7 | Consultant | `submit_for_review` (W15 integration) | ✅ `draft → in_review`; review state's `comments.unresolved = 4` (matches pre-resolve, pre-deepen count) |
| 8 | Partner | resolve the section thread root | ✅ root flips to `resolved`; replies stay attached |
| 9 | System (simulated W9 deepening) | rewrite `synergy_estimate` in-place to a shape that doesn't contain the quoted text | ✅ orphan detector flips `text_range` → `orphaned=true`; section / claim / artifact anchors unaffected |
| 10 | Partner | approve | ✅ `in_review → approved` **with 3 unresolved threads still open** — advisory only, not blocking |

### Headline assertions (11 / 11 PASS)

- ✅ `all_threads_assemble_correctly` — every `parent_comment_id` resolves to an existing row
- ✅ `mention_partner_resolved` — partner_id present in step 1's `mentioned_user_ids`
- ✅ `mention_analyst_resolved` — analyst_id present in step 3's `mentioned_user_ids`
- ✅ `non_member_mentions_ignored` — bogus `@ghost.user` slug did NOT add a sneaky user_id (exactly 1 mention stored on step 1)
- ✅ `claim_anchor_correct` — step 5's `anchor_ref.claim_id == "claim_revenue_1"`
- ✅ `artifact_anchor_correct` — step 6's `anchor_ref.artifact_id` matches the seeded deck row
- ✅ `review_unresolved_count_accurate` — review response's `comments.unresolved` matches the live count at submit time
- ✅ `text_range_orphan_detected_after_deepening` — 1/1 text_range comment flipped to `orphaned=true`; quote no longer appears in the rewritten section
- ✅ `section_claim_artifact_anchors_survive_deepening` — section + claim + artifact roots are NOT marked orphaned (they key on stable identifiers, not quoted strings)
- ✅ `approval_not_blocked_by_unresolved` — partner approved despite 3 open threads; final state `approved`
- ✅ `audit_covers_state_changes` — every state-changing comment action wrote an `audit_events` row (`comment.created` × 4, `comment.replied` × 2, `comment.resolved` × 1)

### Audit completeness

- **Comments**: 6 total — 4 roots (1 section, 1 text_range, 1 claim, 1 artifact) + 2 replies.
- **Audit events** (resource_type=`comment`): 7 rows. Action breakdown:
  - `comment.created` × 4 (one per root)
  - `comment.replied` × 2 (partner reply, analyst reply)
  - `comment.resolved` × 1 (partner resolving the section thread)

Mention-emitted `comment.mention` audit events fire from the API
layer (per W16/D2); the e2e calls services directly so those rows
aren't in this run's audit count. The `comment.mention` path itself
is unit-tested in `test_comments_api.py::test_mention_parsed_and_stored`.

## What works

- **Threaded discussion is live across three anchor classes.**
  Sections (W9 dotted paths), claims (W7+ claim_citations
  registry), artifacts (W10–W13 deliverables) all accept threads
  with the same shape; replies inherit the root's anchor
  automatically so the schema's NOT NULL anchor contract holds
  without burdening the API caller.
- **Mention resolution is canonical and safe.** Email-prefix slug
  (`Sarah.Kim@…` → `@sarah.kim`) is the single form the parser
  matches; collisions get deterministic numeric suffixes. Non-firm
  slugs are silently dropped — there's no way to mention a user
  on a different firm or one who doesn't exist.
- **Orphan detection works as designed.** When the synergy_estimate
  section was rewritten in step 9, the text_range comment whose
  quote no longer appears in the section flipped to
  `orphaned=true`. Section / claim / artifact anchors keep working
  because they key on stable identifiers (path, claim_id,
  artifact_id), not the quoted text.
- **W15 review integration is advisory, not gating.** The review
  GET response now ships `comments: {unresolved: N, total: M}`,
  but step 10 confirms the partner can still approve with 3
  unresolved threads open — the partner decides whether the
  threads are blocking, not the system. (Hard rule from W16/D2.)
- **Cost discipline.** $0.00 LLM cost across the entire cycle (the
  W9 deepening step is simulated by a deterministic in-place
  rewrite — the orphan detector cares about the OBSERVABLE state
  change, not the model that produced it). Wall time: **~7 s**
  for all 10 steps locally.
- **Frontend is wired into both MemoRenderer and ArtifactsRail.**
  Section affordances co-exist with the W9 Deepen button; claim_id
  table cells get an inline 💬 next to the value; artifact cards
  get a 💬 next to the status badge. Thread panel slides in from
  the right, supports reply / edit (author-only) / delete (soft) /
  resolve / unresolve, and renders an orphan banner with the
  original quote on drifted text_range comments.

## What's still open

- **Mention delivery (notifications) — wired in W18.** Today the
  service emits a `comment.mention` audit event per resolved
  mention; W18 consumes those events to drive in-app + email
  notification. The `/api/users/{id}/mentions` cross-engagement
  view (W16/D4) is the pull-side stop-gap for "what's waiting
  for me" until push lands.
- **Element-level artifact commenting (deck-slide, Excel-cell) —
  Phase 5.** Artifact-level only for v1 per the W16/D4 hard rule.
  The schema would need a new anchor_ref shape (e.g.
  `{artifact_id, slide_index}`) and the deck/sheet viewer would
  need element-anchored hover targets — substantial UI work that
  isn't on the critical path for the consulting-firm trust stack.
- **Real-time live updates — Phase 5.** Comments refresh on
  action (and on next mount). No WebSocket presence + no live
  typing indicators. The two-user smoke uses the page-reload /
  refresh-on-mutation pattern.
- **text_range re-anchoring after edits — best-effort orphan
  flagging only in v1.** When a quoted phrase moves slightly (re-
  paragraphing, sentence reordering), the W16/D1 orphan detector's
  whitespace-normalised substring check tolerates cosmetic
  changes; when the phrase is genuinely gone, the comment is
  flagged so the consultant can resolve / edit / delete it. Real
  re-anchoring (CRDT-style range tracking) is a Phase 5 item if
  user feedback warrants it.
- **CommentOverview tab mounting.** The component is built and
  tested (W16/D4) but not yet slotted into the workspace shell.
  The shell is a three-pane layout today; either a fourth pane
  or a tab on the existing right rail is the obvious mount, but
  this is UI-polish work for the consultant who actually uses it,
  not e2e-blocking.

## Schema migrations

- `038_comments.sql` (W16/D1) — `comments` table with
  threaded structure (`parent_comment_id` self-FK), five anchor
  types via CHECK constraint, soft-delete (`deleted_at`),
  resolution columns, mention storage (`mentioned_user_ids JSONB`),
  author/firm/session FKs. Four indexes: session+created,
  parent_comment_id, session+anchor_type, author+created DESC.
- `039_comments_mentions_gin.sql` (W16/D4) — GIN
  (`jsonb_path_ops`) index on `mentioned_user_ids` so the
  cross-engagement `/api/users/{id}/mentions` query is an
  index lookup rather than a sequential scan.

Both migrations cycle cleanly up/down/up; the index sits at ~⅓
the size of the default JSONB GIN opclass and only supports the
`@>` containment query we actually issue.

## Tests

| Day | Tests | Pass |
|---|---|---|
| D1 — service + anchors + orphan | 10 | 10/10 |
| D2 — API + threading + mentions | 11 | 11/11 |
| D3 — MemoRenderer / Thread / Mention / Claim / Orphan UI | 5 files / 15 cases | 15/15 |
| D4 — overview / mentions / artifact (backend) | 5 | 5/5 |
| D4 — CommentOverview / MyMentions (frontend) | 2 files / 8 cases | 8/8 |
| D5 — e2e cycle | 1 runner / 10 steps / 11 headline assertions | 10/10 + 11/11 |

Broader backend regression (excluding NLI / multi-provider
env-dependent suites): **566 passed, 6 skipped**.
Frontend sweep: **106 passed, 27 files**. `tsc --noEmit` clean.

## Cost + timing

| Metric | Value |
|---|---|
| LLM cost (e2e) | $0.00 (W9 deepening step is a deterministic in-place rewrite) |
| Wall time (e2e) | ~7 s |
| Comments produced | 6 (4 roots + 2 replies) |
| Audit events produced | 7 (4 created + 2 replied + 1 resolved) |
| Pre-deepen unresolved | 4 |
| Post-approve unresolved | 3 (one resolved by partner in step 8) |
| Orphaned text_range comments after deepening | 1/1 |
| Section/claim/artifact survivors | 3/3 |

## Decision

- [x] **Ship Week 16.** Threaded discussion is live, anchored at
  three classes, with mentions resolving to canonical slugs,
  orphan detection working as designed under section deepening,
  and the W15 review workflow integrated as advisory (not
  blocking). The collaboration layer now has both the formal
  review gate (W15) AND the informal discussion thread (W16).
- [ ] Iterate.

## Carry-forwards for Week 17

- **Assignment + collaboration state (who owns what).** W17 layers
  ownership / assignment on top of the W15 review gate and W16
  threaded discussion. The data is already there — mentions tell
  you who's tagged on what, review_records tell you who's on the
  reviewer hook — so W17 is mostly the explicit "this thread is
  assigned to X" model + UI.
- **CommentOverview shell mounting.** The component exists; the
  workspace needs one decision (right-pane vs new tab vs modal
  trigger) and a small JSX wire-up.
- **Mention delivery prerequisites for W18.** The
  `comment.mention` events fire from the API today; W18 needs an
  outbound delivery worker (email, in-app) that consumes them.

## Repro

```
python tools/seed_sample_workspace.py        # one-time, cached
python tools/run_week16_e2e.py               # ~7 s, $0.00
```

Re-running is idempotent: bootstrap resets review state, deletes
prior comments + comment audit rows, and reinstates a known
pre-deepen `synergy_estimate` shape so the orphan check is
deterministic across runs.

## Files of record

- `backend/db/migrations/038_comments.sql` — schema (W16/D1)
- `backend/db/migrations/039_comments_mentions_gin.sql` — GIN index (W16/D4)
- `backend/core/comments/anchors.py` — anchor type + validate_anchor (W16/D1)
- `backend/core/comments/orphan.py` — text_range drift detector (W16/D1)
- `backend/core/comments/service.py` — create / reply / edit / delete / resolve (W16/D1)
- `backend/core/comments/mentions.py` — slug parser + audit emission (W16/D2)
- `backend/core/comments/threads.py` — thread assembly + overview grouping + bulk resolve + mentions query (W16/D2 + D4)
- `backend/api/comments.py` — 9 endpoints (W16/D2 + D4)
- `backend/api/users.py` — `/api/users/{id}/mentions` (W16/D4)
- `frontend/components/Comments/*` — 7 components + 7 test files
- `frontend/lib/api/comments.ts` — typed client
- `tools/run_week16_e2e.py` + `backend/eval_runs/week16_e2e/summary.json`

## Hard-rule audit

- ❌ Mentions resolve to wrong users or leak across firms? **No.** Non-member slug dropped (assertion 4); cross-firm 404 covered by W16/D2 unit test.
- ❌ Approval blocked by unresolved comments? **No.** Step 10 partner approved with 3 open threads (assertion 10).
- ❌ Audit misses any comment action? **No.** State-changing actions cover (assertion 11). Mention audit verified in unit tests.
- ❌ Element-level artifact commenting shipped? **No.** Artifact-level only for v1 per W16/D4 hard rule.
- ❌ LLM cost? **$0.00.** Deterministic in-place rewrite stands in for the W9 deepener.
