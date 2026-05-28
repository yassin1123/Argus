# Argus production deploy

A repeatable procedure to stand up a fresh production Argus instance that
meets the W23/W24 security requirements. Target-agnostic: any host with
Docker + a public domain. Provision the managed pieces (Postgres, S3) on
your cloud of choice; the rest is in this directory.

> **Hard rule:** the deploy target MUST provide encryption-at-rest for
> the database and artifact storage *before* any firm data lands. If your
> target can't, stop — that's a pre-launch blocker, not a Day-2 item.

---

## 0. Provision the managed dependencies (encryption-at-rest)

| Dependency | Requirement | Notes |
|---|---|---|
| Postgres | Managed, **encryption-at-rest ON**, TLS | RDS / Cloud SQL / Azure DB — encrypted by default in 2026. Enable automated backups. Create DB `argus` + a least-privilege app role. |
| Object storage | S3 bucket, **default encryption ON** | For source blobs (`ARGUS_S3_*`). |
| Artifact disk | **Encrypted volume** | Mounted at `/app/artifacts`; set `ARGUS_ARTIFACTS_HOST_DIR` to a path on it. |
| Secrets | Managed secret store | Inject as env at runtime; never bake into the image, never log (W23). |
| Domain | DNS A/AAAA -> host | Caddy auto-provisions the TLS cert for it. |

Confirm encryption-at-rest is actually enabled (cloud console) — don't
assume. This is checklist item #1 in `docs/pilot/deploy_verification.md`.

## 1. Configure

```bash
cp deploy/.env.production.example deploy/.env.production
# Fill in every value. ARGUS_MODE=production is the fail-loud switch.
# Generate SECRET_KEY:  openssl rand -hex 32
```

Required (the compose refuses to start without them): `DATABASE_URL`
(sslmode=require), `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `SECRET_KEY`,
`ALLOWED_ORIGINS`, `ARGUS_DOMAIN`, `PUBLIC_API_URL`, `ARGUS_S3_BUCKET`,
`ARGUS_S3_ACCESS_KEY`, `ARGUS_S3_SECRET_KEY`.

## 2. Apply migrations to the managed DB

The dev `initdb.d` hook does NOT run against a managed DB. Apply
migrations explicitly (idempotent + tracked in `schema_migrations`):

```bash
# Postgres needs the vector + uuid-ossp extensions once:
psql "$DATABASE_URL" -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'

DATABASE_URL="<managed dsn>" python deploy/apply_migrations.py --dry-run   # preview
DATABASE_URL="<managed dsn>" python deploy/apply_migrations.py             # apply
```

## 3. Build + start

```bash
docker compose --env-file deploy/.env.production \
    -f deploy/docker-compose.prod.yml up -d --build
```

Services: `backend`, `worker`, `nli_worker`, `frontend`, `redis`, `caddy`
(TLS). On boot, `backend` runs the W23 config validation + the W25
production boot guard: **if the real cross-family verifier is
unavailable, the container crash-loops with a FATAL message** — it does
NOT come up degraded. Watch for it:

```bash
docker compose -f deploy/docker-compose.prod.yml logs -f backend
```

## 4. Verify health

```bash
curl -fsS https://$ARGUS_DOMAIN/health            # liveness (200)
curl -fsS https://$ARGUS_DOMAIN/health/detailed   # all critical checks OK
```

`degraded` must be `false` and `can_run_real_verifier` `true`.

## 5. Production smoke check (all-green gate)

Run the W24 smoke check against the LIVE instance (point DATABASE_URL at
the managed DB, keys in env). A red check blocks the pilot:

```bash
DATABASE_URL="<managed dsn>" ANTHROPIC_API_KEY=... OPENAI_API_KEY=... \
    python tools/pilot_smoke_check.py --json
```

Save the output into `docs/pilot/deploy_verification.md`.

## 6. Onboard the real firm (their content only — seed NOTHING synthetic)

Using the W24 operator CLI against the managed DB:

```bash
export DATABASE_URL="<managed dsn>"

python tools/pilot_setup.py create-firm \
    --name "<Firm Name>" --primary-color "#RRGGBB" \
    --footer-text "<Firm> — Private & Confidential"

python tools/pilot_setup.py add-user --firm <firm-slug> \
    --email partner@firm.com --role firm_admin --name "<Partner>"
# ...repeat for each real consultant/analyst...

python tools/pilot_setup.py ingest-library --firm <firm-slug> \
    --dir /path/to/their/library --category playbook \
    --modes m_and_a_diligence,growth_strategy
```

## 7. Verify isolation + take the baseline backup

```bash
# Isolation: no other firm can see this firm's data (W23). Run the
# tenant-isolation suite, or spot-check via the API as a different firm.
# Baseline backup BEFORE the firm does any work (day-one insurance):
python tools/backup_firm_data.py --firm <firm-slug> \
    --out backups/<firm-slug>-$(date +%F).json
```

## Teardown / rollback

```bash
docker compose -f deploy/docker-compose.prod.yml down        # keep volumes
# Restore a firm from a backup if day-one corrupts anything:
python tools/restore_firm_data.py --in backups/<firm-slug>-<date>.json
```
