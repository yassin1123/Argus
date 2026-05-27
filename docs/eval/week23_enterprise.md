# Week 23 — Enterprise hardening (compressed)

**Status: ship**

> Week 23 hardens the four things a pilot firm needs before
> trusting Argus with confidential client data: tenant isolation
> (verified airtight), hard-delete + retention (client data is
> actually deletable), audit export (accountability), and
> cost/config governance (no surprise bills, no silent degradation
> — the W22 lesson made permanent). SSO is deferred to post-pilot.

## Component check

| Day | Deliverable                                            | Outcome   |
|-----|--------------------------------------------------------|-----------|
| D1  | Tenant isolation hardening (`auth/firm_scope.py`) + 39 cross-firm tests | ship |
| D2  | Hard delete (`core/retention/deletion.py`) + retention sweep + 8 tests   | ship |
| D3  | Audit export (`api/audit_export.py`) + firm budget gates + rate limits + 9 tests | ship |
| D4  | Fail-loud config (`core/config/validation.py`), heuristic-fallback kill, backup/restore + 5 tests | ship |
| D5  | Enterprise e2e (8 scenarios, 2 firms) + security self-review + wrap-up | ship |

Total W23 tests green: **61 passed, 1 skipped** (config + retention
+ cost governance + tenant isolation suites).

## Enterprise e2e — results

Driver: `tools/run_week23_enterprise_e2e.py`. Two synthetic firms
(`w23-e2e-meridian`, `w23-e2e-lumen`). Results captured in
`backend/eval_runs/week23_enterprise/summary.json`.

| # | Scenario        | Outcome | Headline                                                                                            |
|---|-----------------|---------|-----------------------------------------------------------------------------------------------------|
| 1 | isolation       | ✅ ship | 7/7 cross-firm attempts denied with 404; same-firm read continued to work                            |
| 2 | deletion        | ✅ ship | Zero residual rows across 20 firm-scoped tables; artifact file deleted; audit row content-free        |
| 3 | retention       | ✅ ship | Sweep flagged the expired engagement, admin notified, purge approved after grace window               |
| 4 | audit_export    | ✅ ship | 2 Firm A rows exported; 0 Firm B rows; CSV + NDJSON streamed; no payload-text leak                    |
| 5 | budget          | ✅ ship | 80% + 100% notifications fired; new engagements soft-blocked; in-flight session unaffected             |
| 6 | rate_limit      | ✅ ship | 60 engagements in the rolling hour tripped the gate; HTTP 429 with retry_after=3600                    |
| 7 | config          | ✅ ship | Strict mode with missing keys → degraded=True, `assert_real_verifier_required()` raised               |
| 8 | backup_restore  | ✅ ship | 13 rows round-tripped; Firm B IDs absent from archive; deleted rows came back; second restore is noop |

Overall: **8 / 8 ship**.

## Security self-review summary

See `docs/eval/week23_security_review.md` for the full honest
checklist. Headline:

- **Tenant isolation** ✅, **hard deletion** ✅, **retention** ✅,
  **audit export** ✅, **cost controls** ✅, **secrets in env** ✅,
  **TLS in transit** ✅, **backup/restore** ✅, **fail-loud config** ✅.
- **At-rest encryption** — application is deploy-dependent; the
  pilot infra brief documents the assumption that the host disk is
  encrypted. If the pilot firm demands application-level column
  encryption, escalate to a Week 24 infra item.
- **SSO / SAML** — none; pilot runs on email + bcrypt. Post-pilot.
- **External pen-test** — none; pre-GA, not pre-pilot.

## Ship decision

**Ship.** The four pilot-blocking enterprise concerns
(isolation / deletion / audit / cost+config governance) are
addressed and verified end-to-end on two firms. The security
self-review names every deferred item plainly — a boutique
firm's CISO can read it and decide whether they accept the gaps
(SSO + external pen-test + at-rest pending the deploy contract).

## What's deferred to post-pilot (honest)

- **SSO / SAML.** Existing email + bcrypt session auth suffices for
  a first pilot with 3-10 named users under NDA. SCIM provisioning
  + SAML / OIDC land post-pilot.
- **At-rest encryption.** Today: deploy-dependent (LUKS / cloud-
  managed disk encryption assumed). Pre-GA: application-level
  column wrappers via `pgcrypto` if the firm requires it.
- **External pen-test.** Internal review is sufficient for a single
  pilot under NDA. Engage external pen-test as a pre-GA item.
- **Multi-region / HA.** Not needed at pilot scale (single firm,
  single Postgres + worker). Multi-region replication + HA land
  post-pilot when traffic justifies it.

## Week 24 starts with

Pilot readiness. The big-rock items already lined up:

1. **Real-claim calibration gate** (the unresolved W22 carry-over).
   The W22 Fix-Day proved the cross-family ensemble at 0% FP /
   100% red-team on synthetic claims, but real-claim FP rate is
   STILL unmeasured — that's W24's first hard gate. Until it's
   measured, the pilot posture is "ready conditional on labelling
   completion."
2. **Pilot infra brief.** Encryption-at-rest assumptions, the
   ARGUS_MODE deploy contract, runbooks for backup/restore +
   retention sweep + budget overrides + audit export.
3. **Per-pilot dry run.** Stand up a clean instance, seed two
   pilot users (one firm admin, one consultant), walk a real
   engagement end-to-end with a pilot-shaped query, watch for
   failures the synthetic e2e couldn't catch.

Phase 5 Week 24 (pilot readiness) starts next.
