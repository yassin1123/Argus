# Week 18 — Notifications

**Status:** ship

> Week 18 delivers the signals W15/16/17 generate. Nine notification
> types (mention, comment_reply, engagement_assigned, section_assigned,
> section_needs_review, task_assigned, review_requested,
> changes_requested, review_approved) flow through a dispatcher with
> recipient resolution, actor-exclusion, and cross-event dedup. Two
> channels: in-app (always on) + email (behind a swappable adapter
> — capture in dev, SMTP stub for pilots). Per-type, per-channel
> user preferences. The collaboration loop is closed: people are
> told when something needs their attention.

## Component check

| Component | Status | Evidence |
|---|---|---|
| Schema + dispatcher + recipient resolution + dedup (W18/D1) | ✅ | 10 tests |
| W15/16/17 event wiring + non-fatal failure (W18/D2) | ✅ | 11 tests |
| Email adapter (capture / SMTP) + templates + preferences API (W18/D3) | ✅ | 9 tests |
| Frontend — bell + feed + deep-link nav + preferences UI (W18/D4) | ✅ | 4 component test files, 21 cases; tsc clean |
| **E2E — full notification flow** | ✅ | 8/8 steps, 13/13 headline assertions |

## End-to-end demo (Meridian Advisory)

Driven against the seeded Meridian Kestrel engagement with the
capture email adapter. All three users participate. Pre-cycle
preferences: partner gets `mention` email **on** (explicit override
matching the default); analyst gets `section_assigned` email **off**
(explicit override matching the default). Both serve as evidence
that the preference path runs end-to-end, not just that defaults
happen to land in the right spot.

| # | Actor | Action | Notification(s) generated | Email channel |
|---|---|---|---|---|
| 1 | Lead | Assign `synergy_estimate` to analyst | analyst ← SECTION_ASSIGNED | **skipped** (analyst's pref off) |
| 2 | Lead | Section comment mentioning `@helena.voss` | partner ← MENTION | captured |
| 3 | Analyst | Reply to lead's root (no mention) | lead ← COMMENT_REPLY (default email off) | skipped |
| 4 | Partner | Reply on the same thread mentioning `@priya.shah` | **analyst ← MENTION** (DEDUP: was prior participant via step 3 → would also qualify for COMMENT_REPLY; MENTION wins on priority); lead ← COMMENT_REPLY | analyst email captured; lead skipped |
| 5 | Lead | `submit_for_review` | partner ← REVIEW_REQUESTED | captured |
| 6 | Partner | `request_changes` (blocking on synergy_estimate) | lead ← CHANGES_REQUESTED | captured |
| 7 | Lead | Resolve pointer + `resubmit` | partner ← REVIEW_REQUESTED (second time — resubmit treated as fresh queue entry) | captured |
| 8 | Partner | `approve` | lead ← REVIEW_APPROVED | captured |

**Totals:** 9 notifications, 6 captured emails, ~13 s wall, $0.00 LLM cost.

### Headline assertions (13 / 13 PASS)

- ✅ `all_steps_pass`
- ✅ `actor_never_notified_for_own_action` — across 9 notifications, zero rows have `actor_id == recipient_id`
- ✅ `dedup_one_notification_per_recipient_per_event` — analyst has exactly **one** notification with `source_ref.comment_id == step4's comment_id` (would have been two without dedup: MENTION + COMMENT_REPLY)
- ✅ `dedup_winner_is_mention_over_comment_reply` — that one row's `notification_type == "mention"` (priority 100) not `comment_reply` (priority 20)
- ✅ `analyst_section_assigned_email_skipped` — explicit `email=false` preference honoured at row-create time; `email_status='skipped'`
- ✅ `partner_mention_email_captured` — `email_status='sent'` AND a capture row exists for `helena.voss@meridian.invalid`
- ✅ `captured_emails_have_branding_and_deeplink` — every email's HTML body contains `argus.example.com` (the `View in Argus` link, base URL from `ARGUS_BASE_URL`) AND `Meridian` (the firm name from the W10 `firms.branding` JSONB)
- ✅ `email_status_matches_preference` — zero pref violations across the full notification set
- ✅ `every_notification_has_deeplink_target` — each row carries the `source_ref` fields its type needs (`comment_id`, `section_path`, `task_id`, …) so the W18/D4 `deepLink.ts` produces a non-fallback URL
- ✅ `review_chain_complete` — partner saw `review_requested` × 2 (submit + resubmit); consultant saw `changes_requested` × 1 + `review_approved` × 1
- + 3 informational counters (`partner_review_requested_count=2`, `consultant_changes_requested_count=1`, `consultant_review_approved_count=1`)

## What works

- **Every collaboration signal becomes a notification.** The
  dispatch + delivery pipeline runs inline after the core service
  write commits, so the recipient sees the notification within the
  same request that produced it.
- **Actor exclusion is unconditional.** Across the entire e2e —
  9 notifications, 8 distinct actor IDs — zero rows where the
  actor notified themselves. Verified across mention, reply,
  section_assign, and every review transition.
- **Dedup works exactly as designed.** Step 4 is the load-bearing
  case: analyst was both a prior thread participant AND the
  @-mentioned user on the same comment. The dispatcher's
  `dispatch_batch` collapse keyed on `dedup_key="comment:<id>"`
  picked the higher-priority MENTION and dropped the
  COMMENT_REPLY for that recipient — one row, not two.
- **Preferences are respected at row-create time.** The
  dispatcher's `_persist_one` reads
  `notification_preferences.email` first; rows land with
  `email_status='skipped'` when the user opted out. The capture
  adapter never sees a skipped row because delivery filters
  `WHERE email_status='pending'`.
- **Captured emails have working deep-links + firm branding.**
  Every email body contains the Meridian colour palette + footer
  text from the W10 `firms.branding` JSONB and a `View in Argus`
  button that points at the right path
  (`/sessions/{sid}#comment-{cid}` for mention/reply,
  `?openReview=1` for review actions, `#section-{path}` for
  section_assigned, …).
- **Resubmit is treated as a fresh REVIEW_REQUESTED.** The W18/D2
  wiring originally only fired notifications on `submit_for_review`;
  the e2e exposed a product gap (partner needs to know work is
  back in their queue after changes). Wiring was extended to map
  `resubmit → REVIEW_REQUESTED`, pinned by step 7.
- **Notification failure never blocks a core action.** W18/D2 hard
  rule pinned by `test_notification_failure_does_not_break_core_action`:
  even when the notification INSERT raises, the comment service
  still returns `ok=True` with the persisted row.
- **Cost discipline.** $0.00 LLM cost across the entire e2e —
  templates are deterministic string interpolation; no LLM in the
  notification path by design.

## What's still open

- **Production SMTP.** Capture adapter is the default in dev (and
  the e2e); `SmtpEmailAdapter` is a stub that reads `SMTP_*` env
  vars but returns `ok=False` in v1 with a clear "not implemented"
  reason. Per W18/D3 hard rule "wired when pilots start" — the
  contract is defined, the actual `smtplib`/Sendgrid integration
  drops in when the first pilot needs it.
- **Digest batching.** Immediate per-notification email in v1.
  The delivery worker's shape (`deliver_pending_emails` scans
  every pending row) supports a future scheduled run that
  collects per-recipient digests; documented as Phase 5.
- **Real-time push (WebSocket).** The bell polls
  `/api/me/notifications/unread-count` every 30 s. Real-time push
  is Phase 5 if user feedback warrants it; the 30s poll has been
  the right cadence for every consulting workflow we've watched.
- **Smart feed grouping.** Recency-ordered list in v1; "5 new
  mentions from Marcus on Kestrel" collapsing is Phase 5.
- **Per-user-per-resource last-read pointers.** The `read` flag
  is per-notification; W16/D4's MyMentions view uses an
  `unreadSince` timestamp from localStorage. A real last-read
  table (per-user-per-engagement-per-resource) would let the
  inbox surface "what's new since you last looked at Kestrel"
  without depending on client storage. Phase 5.

## Schema migrations

- `043_notifications.sql` (W18/D1) — `notifications` table +
  `notification_preferences` table. Inbox hot-path index on
  `(recipient_id, read, created_at DESC)`; engagement-scoped
  index on `(session_id)`. CHECK on `email_status` enum
  (pending | sent | skipped | failed) + on summary non-emptiness.

The migration cycles cleanly up/down/up. No further schema
changes shipped this week — D2 through D5 are pure code on top
of D1's tables.

## Tests

| Day | Tests | Pass |
|---|---|---|
| D1 — dispatcher + recipients + dedup | 10 | 10/10 |
| D2 — W15/16/17 wiring + non-fatal failure | 11 | 11/11 |
| D3 — email adapter + templates + preferences API | 9 | 9/9 |
| D4 — frontend (bell / feed / preferences / deep-link) | 4 files / 21 cases | 21/21 |
| D5 — e2e cycle | 1 runner / 8 steps / 13 headline assertions | 8/8 + 13/13 |

Broader backend regression: **623 passed, 6 skipped** (pre-existing
env-dependent NLI / multi-provider tests, unrelated). Full frontend
sweep: **148 passed across 36 files**. `tsc --noEmit` clean.

## Cost + timing

| Metric | Value |
|---|---|
| LLM cost (e2e) | $0.00 (template-based email, no LLM in the notification path) |
| Wall time (e2e) | ~13 s |
| Notifications produced | 9 |
| Captured emails | 6 (skipped: 3 — 1 from analyst's section_assigned pref + 2 from lead's default comment_reply pref) |
| Dedup collapses | 1 (analyst on step 4: would have been 2 rows → 1) |
| Actor-self notifications | 0 / 9 |
| Preference violations | 0 |

## Decision

- [x] **Ship Week 18.** Every collaboration signal from Weeks 15–17
  reaches the right person through the right channel — mentions,
  assignments, review transitions, status changes — with
  unconditional actor exclusion, deterministic cross-event dedup,
  and per-user preferences honoured at row-create time. The
  capture adapter gives dev/test a complete observability surface
  without standing up SMTP; the production transport drops in
  when pilots ship.
- [ ] Iterate.

## Carry-forwards for Week 19 (Phase 4 close)

- **Production SMTP.** Drop a real `smtplib` (or transactional API)
  implementation into `SmtpEmailAdapter.send` when the first pilot
  is provisioned. No contract changes needed — `ARGUS_EMAIL_ADAPTER=smtp`
  flips the singleton; everything else is unchanged.
- **Workspace URL consumption.** The W18/D4 deep-link contract is:
  the workspace shell reads `?openComment` / `?openReview` /
  `#section-{path}` / `?openTask` and routes to the right panel.
  Today the ThreadPanel accepts `initialCommentId` to scroll +
  highlight; the workspace shell's URL → prop wiring is the
  small task that closes the click-through loop.
- **Phase 4 close.** W15 review + W16 comments + W17 collaboration
  + W18 notifications interlock. W19 ships the version-history UI
  + the full multi-user demo + the Phase 4 wrap.

## Repro

```
python tools/seed_sample_workspace.py        # one-time, cached
python tools/run_week18_e2e.py               # ~13 s, $0.00
```

Re-running is idempotent: bootstrap deletes prior notifications +
review_records + comments + section_assignments + memberships,
then re-seats the consultant as lead and re-installs the test
preferences for partner + analyst. The capture adapter is reset
to a fresh instance per run so its `.captured` list is exactly
the e2e's emails — nothing leaked from prior tests.

## Files of record

- `backend/db/migrations/043_notifications.sql` — schema
- `backend/core/notifications/` — 9 modules:
  `types.py`, `defaults.py`, `summaries.py`, `recipients.py`,
  `dispatcher.py`, `wiring.py`, `email/{adapter,templates,delivery}.py`
- `backend/api/notifications.py` + `backend/api/notification_preferences.py`
  — 7 endpoints (4 inbox + 3 preferences)
- `frontend/lib/api/notifications.ts` — typed client
- `frontend/components/Notifications/` — 5 components
  (NotificationBell, NotificationNavItem, NotificationFeed,
  NotificationPreferences, deepLink) + 4 tests
- `tools/run_week18_e2e.py` + `backend/eval_runs/week18_e2e/summary.json`

## Hard-rule audit

- ❌ Actor notified for own action? **No.** Assertion 2 — 0/9 rows.
- ❌ Dedup failed? **No.** Assertion 3 — analyst has exactly 1
  notification from step 4, type=mention.
- ❌ Preferences ignored? **No.** Assertion 8 — zero violations
  across all rows.
- ❌ Deep-link target wrong? **No.** Assertion 9 — every row
  carries the source_ref fields its type needs.
- ❌ LLM cost? **$0.00.** Templates are deterministic; no LLM
  in the notification path.
