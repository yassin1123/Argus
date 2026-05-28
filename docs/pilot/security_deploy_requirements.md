# Pilot security & deploy requirements

The honest answer to the at-rest-encryption question deferred from
Week 23, plus the full deploy checklist a pilot firm's security
reviewer can sign off against.

---

## At-rest encryption — the honest answer

**For a first pilot, at-rest encryption is a DEPLOY requirement, not an
application feature.**

Argus does not encrypt individual fields in the application layer, and
for a first pilot it shouldn't. The correct, sufficient control is:

- A **managed Postgres with encryption-at-rest enabled** (AWS RDS,
  GCP Cloud SQL, Azure Database — all encrypt at rest by default in
  2026, backed by the provider's KMS).
- **Encrypted disks** for the artifact storage volume (the filesystem
  or object store where `export_artifacts.file_path` lives — e.g. an
  encrypted EBS volume, or S3/GCS with default bucket encryption).

This protects the data the way it actually gets exfiltrated in
practice — a stolen disk, a snapshot leak, a decommissioned drive.
Application-level field encryption (encrypting the memo prose in the DB
with app-held keys) adds key-management complexity and breaks
search/indexing, for a marginal gain over full-disk + managed-DB
encryption. **It is overkill for a first pilot.**

### If Blackmont's reviewer demands application-level field encryption

That's a legitimate ask for some regulated buyers — but it is a
**Phase 6 / GA item, not a Week 24 build.** Document it, scope it
post-pilot:

- It would mean envelope-encrypting specific columns (e.g.
  `reports.consulting_payload`, `evidence_objects.quote`) with a KMS
  data key, decrypting in the application on read.
- It has real costs: key rotation, the loss of in-DB search on
  encrypted columns, and a performance hit on every read.
- **We will not build it during the pilot.** If the reviewer makes it a
  hard gate for the pilot itself (not GA), that's a deal-scope
  conversation for Yassin + Blackmont, not an engineering task this
  week.

---

## Deploy checklist (the reviewer signs off against this)

| # | Control | Requirement | How |
|---|---------|-------------|-----|
| 1 | **DB at-rest** | Managed Postgres, encryption-at-rest ON | RDS/Cloud SQL default; confirm in the console |
| 2 | **Artifact storage at-rest** | Encrypted volume / bucket | Encrypted EBS or S3/GCS default encryption |
| 3 | **In transit** | TLS on every external surface | TLS-terminating load balancer in front of the frontend + API; HSTS |
| 4 | **DB in transit** | TLS to Postgres | `sslmode=require` in `DATABASE_URL` for the managed DB |
| 5 | **Secrets** | In a managed secret store, never in the image | AWS Secrets Manager / GCP Secret Manager / equivalent; injected as env at runtime |
| 6 | **Config mode** | `ARGUS_MODE=pilot` (strict) | The W23 fail-loud refuses heuristic substitution + crashes on a missing verifier key |
| 7 | **Boot validation** | `/health/detailed` all-critical-OK | The W23 boot report; the smoke check (§ runbook) gates handover |
| 8 | **Backups** | Automated, encrypted, tested restore | Managed DB automated backups + a tested `tools/restore_firm_data.py` round-trip |
| 9 | **Tenant isolation** | Verified | W23/D1 — `assert_firm_access`, 404 anti-enumeration, 39 cross-firm tests |
| 10 | **Audit trail** | Append-only, exportable | W23/D3 audit export; revoke `UPDATE/DELETE` on `audit_events` from the app DB role in prod |
| 11 | **Least-privilege DB role** | App connects as a non-superuser | Grant only DML on app tables; deny DDL + audit mutation |

### What's application-level (already built) vs deploy-level (the firm's infra)

**Application-level — shipped, verified in code:**
- Tenant isolation + anti-enumeration (W23/D1)
- Hard delete + retention + right-to-deletion (W23/D2)
- Audit log + content-free export (W23/D3)
- Cost governance + rate limits + cost-burn alerts (W23/D3 + W24/D4)
- Fail-loud config + no silent verifier degrade (W23/D4)
- Backup/restore round-trip (W23/D4)
- Secrets read from env, never logged (W20 redaction + W23 tests)

**Deploy-level — the firm's / operator's infrastructure responsibility:**
- At-rest encryption (DB + artifact storage) — checklist #1, #2
- TLS termination + HSTS — #3, #4
- Managed secret store — #5
- Backup automation + the least-privilege DB role + audit-table
  immutability — #8, #10, #11

---

## Deferred to Phase 6 / GA (named, not hidden)

- **Application-level field encryption** (see above) — only if a buyer
  makes it a hard requirement.
- **SSO / SAML** — pilot runs on email + bcrypt session auth (W23
  security review).
- **External penetration test** — pre-GA, not pre-pilot.
- **Multi-region / HA** — not needed at pilot scale.

A reviewer reading this should come away with a clear yes/no per
control and a short, honest list of what we've consciously deferred —
not a clean-looking checklist that hides the gaps.
