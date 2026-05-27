# Week 23 — Security self-review

> The honest checklist a boutique firm's security reviewer would
> walk before agreeing to a pilot. Each item: **what we have**,
> **how it's verified**, and **what's deferred** — the deferred
> column is the load-bearing one. A clean-looking review that hides
> deferred items is worse than an honest one with a clear deferred
> list.

Run date: **2026-05-27**. Verified against the
`tools/run_week23_enterprise_e2e.py` summary
(`backend/eval_runs/week23_enterprise/summary.json`) plus the 61
W23 unit/integration tests.

---

## 1. Tenant isolation — ✅ verified

**Status.** Centralised at `backend/auth/firm_scope.py::assert_firm_access`.
Every firm-scoped route routes a `(user, resource_firm_id)` pair
through this helper. Cross-firm reads return **HTTP 404** (anti-
enumeration: the response is indistinguishable from "resource
doesn't exist"). A `security.cross_firm_denied` event is emitted
on every deny.

**Verified by.**
- 39 cross-firm scenarios in `backend/tests/test_tenant_isolation.py`
  cover sessions / comments / artifacts / payload versions /
  memberships / engagement tasks / notifications.
- W23 enterprise e2e — scenario `isolation` ran 7 cross-firm
  reads from Firm B's admin against Firm A and blocked 7/7.
  Same-firm read continued to work (sanity).
- Defence-in-depth at the permission layer:
  `backend/auth/permissions.py::_engagement_firm_matches_user`
  re-checks the firm match independently of the guard, so a future
  route that forgets the guard still can't grant a cross-firm
  capability.

**Honest gaps.** None known on the API surface. Direct DB access
is governed by the deploy's Postgres credentials — a single shared
DB user (the MVP shape) means a DBA query bypasses the guard.
This is a deploy/operations concern, not an application concern;
the pilot infra brief calls it out.

---

## 2. Data deletion — ✅ hard purge, verified

**Status.** `backend/core/retention/deletion.py::purge_engagement`
hard-deletes across 20 firm-scoped tables in one transaction.
Artifact files on disk are unlinked **before** their DB rows are
removed (so a mid-purge crash never strands files pointing nowhere).
Each per-table DELETE runs in its own SAVEPOINT, so a missing
optional table on partial schemas doesn't abort the rest of the
purge. A `purge_audit_log` row records counts + actor + reason
— never claim text, evidence text, or memo prose.

**Verified by.**
- 8 tests in `backend/tests/test_retention_deletion.py`.
- W23 enterprise e2e — scenario `deletion` purged a Firm A
  engagement that had evidence + comments + a payload version +
  an on-disk artifact file. After the purge: **zero residual rows
  across all 20 tables**, the artifact file was gone, and the
  `purge_audit_log` entry contained no payload-content keys.

**Honest gaps.** The 5-minute Postgres WAL retention on a default
deploy means a recently-purged row is still recoverable by a DBA
running `pg_waldump` against the WAL stream. For pilot use that
is acceptable (purge is an application-level guarantee, not a
forensic-level one); for a future "right to be forgotten"
compliance posture, document the WAL window in the pilot infra
brief.

---

## 3. Data retention — ✅ configurable, grace period

**Status.** Per-firm `retention_days` (NULL = keep indefinitely;
firms opt-in). Default minimum is 7 days (prevents accidental
same-day purges). The sweep runs in three passes:

  1. **flag** — `retention_flagged_at` set; firm_admin gets a
     `RETENTION_PURGE_SCHEDULED` notification.
  2. **grace** — `DEFAULT_RETENTION_GRACE_DAYS = 14` days between
     flag and actual purge.
  3. **purge** — `purge_engagement(reason="retention_sweep")`.

**Verified by.**
- Decision-table tests in `test_retention_deletion.py` cover
  noop / flag / purge transitions.
- W23 enterprise e2e — scenario `retention` backdated a Firm A
  engagement by 100 days, set `retention_days = 30`, ran the
  sweep, confirmed the flag + admin notification, then simulated
  "now + grace + 1d" and confirmed the decision flipped to
  `purge` and the rows were actually removed.

**Honest gaps.** None. Retention is opt-in (no firm has data
auto-purged just because they forgot the docs).

---

## 4. Audit trail + export — ✅

**Status.** `audit_events` is append-only at the application layer
(the code never issues `UPDATE` / `DELETE`). The `GET
/api/admin/firms/{id}/audit-export` endpoint streams CSV or NDJSON,
scoped to the requesting firm only. A firm_admin can export only
their own firm (system_admin can export any). Payloads pass
through `_strip_payload` with an allow-list (`_ALLOWED_PAYLOAD_KEYS`)
so a future writer that puts claim text into the payload by
mistake **cannot** leak it via the export.

**Verified by.**
- 9 tests in `backend/tests/test_cost_governance.py` /
  `test_audit_export.py` (see also W23/D3 commits).
- W23 enterprise e2e — scenario `audit_export` planted two Firm A
  events and one Firm B event (Firm B's payload carried a
  canary string `FIRM_B_CONFIDENTIAL_should_not_appear`).
  The export returned 2 rows scoped to Firm A; **0 Firm B rows**;
  the canary string did **not** appear in the serialised export.

**Honest gaps.** Audit export is **firm-scoped**, not session-
scoped — a firm_admin sees every audit event for their firm, not
just for engagements they own. This is intentional (firm_admin
== legal/compliance contact for the firm) and matches the
permission model. Document it for the pilot security review.

To delete an audit row, a DBA must do it manually with a DELETE
that bypasses the application — there is no application path that
does so. This is correct for append-only audit semantics.

---

## 5. Cost controls — ✅ firm budget + rate limit

**Status.**

- **`firms.monthly_budget_usd`** — firm-wide monthly cap. 80% +
  100% thresholds notify firm_admin (dedup'd per month). At 100%,
  **new** engagement creation is soft-blocked (HTTP 402); in-flight
  engagements continue to completion (W23/D3 hard rule — a budget
  cannot kill an in-flight engagement).
- **`firms.session_cost_ceiling_usd`** — per-engagement backstop
  (default $5.00). The orchestrator consults this between pipeline
  stages and stops gracefully on trip.
- **Rate limits** — 60 engagements/hour and 30 expensive-endpoint
  calls/minute per firm. Returns HTTP 429 with `retry_after_seconds`.

**Verified by.**
- 9 tests in `backend/tests/test_cost_governance.py`.
- W23 enterprise e2e — scenario `budget` drove Firm A to $8 (80%
  threshold fired), then $10.50 (100% fired + `blocks_new_engagements`
  flipped + per-session ceiling tripped at $10.50 > $5.00). The
  in-flight session remained in `status='ready'` (was never
  killed). Scenario `rate_limit` inserted 60 sessions in the
  last hour and confirmed the next request would be blocked with
  `retry_after_seconds=3600`.

**Honest gaps.** Budgets reset on the calendar month boundary
(UTC). A firm spanning multiple timezones may see the reset off
their local midnight; surface in the dashboard if firms ask.

---

## 6. Secrets — ✅ env-based, never logged

**Status.** Every secret (LLM API keys, DB credentials, SMTP
password) is read from environment variables. The W20/D1
structured-logging stack has a redact denylist; `_strip_payload`
in audit export is a second line of defence. Tests cover both
paths.

**Verified by.**
- `test_secrets_never_in_logs` in `test_config_hardening.py`
  asserts that a synthetic ANTHROPIC_API_KEY value never appears
  in captured log output across boot + a request.
- W23 enterprise e2e — scenario `config` re-validates boot in
  strict mode with `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` unset.
  The resulting `ConfigReport` surfaces "MISSING — required for
  cross-family verification" but **never the key value itself**
  (there is none, but the same code path runs the redactor).

**Honest gaps.** Container env vars are visible to anyone with
shell into the container (the deploy's `docker exec`). This is a
standard ops concern; the pilot infra brief recommends running
under a non-root account + restricting `docker exec` to the ops
team.

---

## 7. Encryption — TLS in transit ✅; at-rest depends on deploy

**Status.**

- **In transit.** Every external surface (the Next.js frontend,
  the FastAPI backend) sits behind TLS in the pilot deploy
  template. The container-to-container DB hop is `tcp://db:5432`
  on the Docker network — not TLS-wrapped. For pilot use that's
  acceptable (the network is internal-only); a network-layer
  attacker would already have host root.
- **At rest.** **Honest answer: depends on the deploy.** The
  application does NOT encrypt cell-level data. The pilot infra
  brief assumes:
    - The Postgres data volume sits on an encrypted disk (LUKS /
      cloud-provider managed encryption — both are standard).
    - The artifact filesystem on which `export_artifacts.file_path`
      writes is on the same encrypted volume.
  If the pilot firm requires application-level at-rest encryption
  (pgcrypto column wrappers, etc.), that's a **Week 24 infra
  item** — surface the requirement before pilot start.

**Honest gaps.** No pgcrypto column wrappers today. The pilot
brief documents the assumption that the host disk is encrypted.
**If a firm pushes back on this, treat it as a pre-pilot blocker
and add at-rest column encryption to the W24 backlog.**

---

## 8. Auth — session auth ✅; SSO deferred

**Status.** bcrypt password hashes + opaque session tokens stored
in `sessions_auth`. CSRF is not required because we use the
session-cookie + same-origin frontend model. Login is rate-limited
by SlowAPI (mounted in `backend/main.py`).

**Honest gaps. SSO / SAML is deferred to post-pilot.** A boutique
firm running its first pilot with Argus can stand up a small set
of accounts (3-10 users) against the existing email/password flow.
SCIM provisioning and SAML are listed in `docs/eval/week24_pilot_readiness.md`
(to be written W24) as post-pilot work.

Password reset flow exists but goes through the W18 email adapter
(`capture` for dev/pilot; `smtp` in pilot+). A firm requiring
their own IdP from day one should be told plainly that we don't
have SSO yet — running on email/password is acceptable for a
first pilot, not for a GA deploy.

---

## 9. Backup / restore — ✅ round-tripped

**Status.** `backend/core/backup/archive.py::backup_firm`
exports every firm-scoped table to a portable JSON archive.
`restore_firm` re-inserts in topological order with `ON CONFLICT
(id) DO NOTHING` for idempotency. The archive is firm-scoped — a
backup of Firm A cannot leak Firm B rows.

**Verified by.**
- `test_backup_restore_round_trip` in `test_config_hardening.py`.
- W23 enterprise e2e — scenario `backup_restore`:
    - Backed up Firm A (13 rows across users + sessions +
      reports + evidence + comments + payload versions +
      notifications + purge_audit_log).
    - Confirmed Firm B's session ID did NOT appear in the
      archive (canary check).
    - Deleted 1 comment + 3 evidence rows from Firm A.
    - Called `restore_firm(archive)` — all 4 deleted rows came
      back.
    - Called `restore_firm(archive)` again — 0 inserts
      (idempotent).
    - Full JSON round-trip preserved `total_rows()`.

**Honest gaps.** Backups carry bcrypt password hashes (not
plaintext) so a restored user can still log in. If a firm prefers
that restores force a password reset, run `UPDATE users SET
password_hash = '' WHERE id IN (...)` post-restore. Document in
the runbook.

---

## 10. Fail-loud config — ✅ no silent degradation

**Status.** `ARGUS_MODE = test | pilot | production`. In pilot/
production (strict), `validate_at_boot()` surfaces every critical
config check on a cached `ConfigReport`; the `/health` endpoint
reads from this cache. `assert_real_verifier_required()` raises
`VerifierUnavailable` at every call site that would otherwise
construct a `HeuristicVerifier` — the W22 silent-fallback bug
class is **permanently impossible**.

**Verified by.**
- 5 tests in `test_config_hardening.py`.
- W23 enterprise e2e — scenario `config` unset
  `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` in pilot mode, re-ran
  `validate_at_boot()`, confirmed `degraded=True` +
  `can_run_real_verifier=False`, and confirmed
  `assert_real_verifier_required()` raised
  `VerifierUnavailable`.

**Honest gaps.** None. This is the strongest surface in the
review — it's the one the W22 incident wrote into our blood.

---

## 11. Pen-test / external audit — NOT yet done

**Status. Open. Pre-GA, not pre-pilot.**

The application has been internally reviewed against:
- OWASP Top 10 — covered by the FastAPI + Pydantic + auth-router
  stack; SQL injection is mitigated by exclusive use of
  parametric asyncpg queries (verified by grep).
- The tenant-isolation, deletion, retention, audit, and cost
  surfaces enumerated above.

**Honest gap.** **No external pen-test has been conducted.** This
is acceptable for a first pilot with a single boutique firm under
NDA, but is a hard blocker for GA. The Week 24 plan lists "engage
external pen-test" as a pre-GA item.

---

## Summary — what a security reviewer can take to their CISO

| Concern                  | Status        | Deferred? |
|--------------------------|---------------|-----------|
| Tenant isolation         | ✅ verified   | —         |
| Hard deletion            | ✅ verified   | —         |
| Retention + grace        | ✅ verified   | —         |
| Audit trail + export     | ✅ verified   | —         |
| Cost controls            | ✅ verified   | —         |
| Secrets in env           | ✅ verified   | —         |
| TLS in transit           | ✅            | —         |
| At-rest encryption       | ⚠ deploy-dependent | Document for pilot infra; W24 if firm demands column-level |
| Session auth             | ✅            | —         |
| SSO / SAML               | ❌ none       | Post-pilot |
| Backup / restore         | ✅ verified   | —         |
| Fail-loud config         | ✅ verified   | —         |
| External pen-test        | ❌ none       | Pre-GA, not pre-pilot |

**Pilot-blocking gaps: none, conditional on the pilot firm
accepting deploy-dependent at-rest encryption + email/password
(no SSO).**

**Pre-GA backlog:** SSO / SAML, external pen-test, application-
level at-rest column encryption, multi-region / HA.
