# Production deploy verification

The filled-in checklist confirming a production Argus instance meets
every W23/W24 security requirement before a real firm's data lands. This
is what a firm's security reviewer is shown.

**Two-column status:** *Verified in build* = proven in code/CI/local
against the real verifier; *Verify on target* = a per-deploy step the
operator confirms against the live managed instance and records here.

---

## A. Verified in build (proven, repeatable)

| # | Control | Status | Evidence |
|---|---|---|---|
| A1 | Fail-loud config: production refuses to boot when the real cross-family verifier is unavailable | ✅ | `core/config/validation.py::enforce_boot_or_exit`; wired in `main.py`. Verified: `ARGUS_MODE=production` + missing keys → `SystemExit` (crash-loop); with keys → boots. |
| A2 | Heuristic verifier CANNOT run in strict mode | ✅ | W22/W23 `assert_real_verifier_required`; W24/D1 gate. The boot guard (A1) additionally refuses to start prod degraded. |
| A3 | Tenant isolation (cross-firm → 404, anti-enumeration) | ✅ | W23/D1 `auth/firm_scope.py`; 39 cross-firm tests; dress-rehearsal isolation 2/2 blocked. |
| A4 | Hard delete + retention (data is actually deletable) | ✅ | W23/D2; dress rehearsal purge → 0 residual rows. |
| A5 | Audit log append-only + content-free export | ✅ | W23/D3; dress rehearsal export 5 rows, no content leak. |
| A6 | Secrets read from env, never logged | ✅ | W20 redaction + W23 `test_secrets_never_in_logs`. Prod compose has NO insecure defaults — required vars use `${VAR:?}`. |
| A7 | Migrations apply to a managed (non-initdb) Postgres | ✅ | `deploy/apply_migrations.py` — verified: 49 migrations applied to a fresh DB, idempotent on re-run, tracked in `schema_migrations`. |
| A8 | TLS termination + HSTS | ✅ (config) | `deploy/Caddyfile` auto-provisions Let's Encrypt for `ARGUS_DOMAIN`; HSTS 1y + security headers. Cert issuance confirmed on target (B-row). |
| A9 | Real pipeline + real verifier produce verified deliverables | ✅ | W24/D5 dress rehearsal: 2 engagements, 30 verified claims, 6/6 deliverables each, $0.69. |
| A10 | Smoke check tool (the all-green gate) | ✅ | `tools/pilot_smoke_check.py`; 3 tests; latest local run 7/7 green (below). |

### Latest smoke-check output (local, real verifier)

```
overall: green   summary: {green: 7, yellow: 0, red: 0, total: 7}
  GREEN config              mode=...; cross-family verifier available; all critical config present
  GREEN database            Postgres reachable
  GREEN observability       metric written + read back
  GREEN artifact_generators all 5 exporters registered + memo = 6 deliverables
  GREEN notifications       subsystem importable + table queryable
  GREEN audit_log           audit row appended + read back
  GREEN sample_engagement   pipeline produces deliverables (>=5 ready artifacts)
```

---

## B. Verify on target (per-deploy — operator fills in at launch)

These can only be confirmed against the actual provisioned instance.
Record the result + date here before the firm starts work.

| # | Control | How to confirm | Result |
|---|---|---|---|
| B1 | Postgres encryption-at-rest ENABLED | Cloud console (RDS/Cloud SQL "encryption" = on) | ☐ pending |
| B2 | DB connection uses TLS | `DATABASE_URL` has `sslmode=require` | ☐ pending |
| B3 | Object storage (S3) default encryption ON | Bucket properties → default encryption | ☐ pending |
| B4 | Artifact volume encrypted | `ARGUS_ARTIFACTS_HOST_DIR` on an encrypted disk | ☐ pending |
| B5 | Secrets from managed store, not files/image | injected at runtime; `git grep` shows no secrets committed | ☐ pending |
| B6 | TLS cert issued for the domain | `curl -fsS https://$ARGUS_DOMAIN/health` returns 200 over HTTPS | ☐ pending |
| B7 | `/health/detailed`: `degraded=false`, `can_run_real_verifier=true` | curl the endpoint on the live host | ☐ pending |
| B8 | Production smoke check 7/7 green against the LIVE instance | `python tools/pilot_smoke_check.py --json` with prod `DATABASE_URL` | ☐ pending |
| B9 | Least-privilege DB role (DML only; no DDL/audit mutation after migrate) | grant review on the managed DB | ☐ pending |
| B10 | Automated encrypted DB backups enabled | managed-DB backup settings | ☐ pending |

---

## C. Real-firm onboarding record (operator fills in)

Run against the live instance using `tools/pilot_setup.py` — **their
content only, seed nothing synthetic** (W24/W25 hard rule).

| Item | Value / result |
|---|---|
| Firm name + slug | ☐ |
| Branding (primary color / footer / logo) | ☐ |
| Users added (email + role) | ☐ |
| Library docs ingested (count, formats, ready/failed) | ☐ |
| Isolation verified for this firm specifically | ☐ |
| Baseline backup taken (path + timestamp, BEFORE first engagement) | ☐ |

---

## Deferred to post-pilot (named, not hidden)

SSO/SAML; application-level field encryption (deploy-level at-rest is the
pilot-appropriate control); external penetration test (pre-GA);
multi-region/HA. See `docs/pilot/security_deploy_requirements.md`.
