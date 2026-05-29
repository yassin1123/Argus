# Argus v1.0 — scope

What v1.0 is, and what it explicitly is not. The line is drawn by one
test: **is it in the pilot and working? In. Is it a known deferral?
Post-1.0, named.** v1.0 is earned — a real firm is using it, with
documented bounds — not self-declared by feature completeness.

---

## In v1.0 (built, verified, in the pilot)

### The verification spine
- Claim-level source binding (the analyst cannot emit an ungrounded claim).
- **Cross-family verification**, enforced at boot: the writer's family ≠
  the verifier's family (Anthropic synthesis, OpenAI gpt-4o judge), plus
  a DeBERTa-v3 cross-encoder + lexical/numeric overlap — a three-signal
  ensemble that only downgrades.
- **The GREEN-gated verifier** with the **"verified (conservative)"
  posture**: on the W24/D1 real-claim gate (61 human-labelled real
  claims) it measured **0% false-positives-on-supported** and **100%
  recall-on-insufficient**. The trade-off is deliberate conservatism
  (it under-credits genuinely-supported claims; recall-on-supported ~27%)
  — it never wrongly blesses, so a human reviews flagged claims.
- Fail-loud config: in production a missing key / DeBERTa **crash-loops**
  the boot. The heuristic substitute can never run in prod (the W22 bug
  class, made impossible).

### The six-artifact deliverable suite
- Memo, one-pager (HTML/PDF), deck (PPTX), Excel model (XLSX), client
  email (MD/HTML/PDF), interview guide (MD/HTML/PDF). Every factual claim
  in every artifact traces to a source passage. Verified end-to-end in
  the W24/D5 dress rehearsal (6/6 deliverables per engagement).

### Firm knowledge + layered modes
- Per-firm library (playbooks, sector primers, prior reports,
  methodologies), chunked + embedded + firm-scoped, retrievable across
  engagements, never leaking across firms.
- Built-in consulting modes (general, market entry, due diligence,
  growth strategy, M&A diligence) + per-firm mode overrides (layered
  resolution).
- Structured frameworks (2×2, Porter's Five Forces, Value Chain),
  Pyramid + MECE checks.
- Firm branding on every deliverable.

### The full collaboration layer
- Manager review workflow (draft → in_review → changes_requested →
  approved → delivered), role-gated, structured feedback + pointer
  resolution, lock-on-approval with auto-revert.
- Comments anchored to section / claim_id / artifact / text_range,
  @-mentions, orphan detection.
- Per-section ownership + work-status + my-work queue + tasks.
- Notifications (in-app + email adapter) across the engagement events,
  with actor-exclusion + dedup.
- Version history: every payload-changing action appends a version;
  diff (per-section + word-level) + restore (approval-aware).

### Observability
- Structured logs + trace IDs, metrics, cost ledger, request-lifecycle
  trace assembly, the admin observability dashboard, and the W25
  **live-pilot watch view** + operator alerting (failure / error-spike /
  budget / verification-anomaly).

### The four enterprise pillars
- **Tenant isolation** — centralized guard, cross-firm → 404
  (anti-enumeration), 39 cross-firm tests.
- **Data retention + hard deletion** — configurable per-firm window +
  grace; purge across 20 tables; content-free purge audit.
- **Audit export** — append-only audit log; firm-scoped, content-free
  CSV/NDJSON export.
- **Cost governance** — per-firm monthly budget (soft-stop at 100%) +
  per-session ceiling + rate limits + operator cost-burn alerts.

### Pilot operability
- Onboarding flow (in-app wizard + operator CLI), template briefs,
  pilot getting-started guide, operator runbook, pre-flight smoke check,
  backup/restore, deploy config (managed Postgres + TLS + secrets +
  fail-loud), feedback instrumentation (per-claim, per-artifact, edit
  telemetry, weekly check-in) and the live signal aggregation.

---

## Explicitly post-1.0 (named, not hidden)

These are real deferrals. A clean-looking scope that hides them would be
worse than this honest list.

| Deferred item | Why it's out of 1.0 |
|---|---|
| **SSO / SAML / SCIM** | Pilot runs on email + bcrypt session auth. Existing auth suffices for a first firm; IdP integration is post-pilot. |
| **Application-level field encryption** | Deploy-level at-rest encryption (managed DB + encrypted volumes, W24) is the pilot-appropriate control. App-level column encryption is a GA item, only if a buyer requires it. |
| **External penetration test / SOC 2 audit** | Internal review only for a first pilot under NDA. Pre-GA, not pre-pilot. |
| **Companies House OCR** | Image-only filings aren't ingested today; a known ingestion gap to address if the pilot firm's content needs it. |
| **Multi-instance / cache invalidation / HA / multi-region** | Single-instance is fine at pilot scale. |
| **Notification digests + real-time push** | In-app feed + email adapter ship; batched digests + websockets are later. |
| **Element-level artifact commenting + text-range re-anchoring** | Section/claim/artifact anchoring ships; finer-grained anchors are later. |
| **Verifier recall improvement (the conservative-trait work)** | The 1.0 verifier is deliberately conservative (over-flags). Reducing over-flagging *without* raising the false-positive rate is a Phase-6 quality track, informed by the live claim-feedback stream. |
| **Whatever the pilot's edit-rate finding points at** | The live edit-rate signal (W25/D3) will name specific draft-quality gaps; those become post-1.0 work once there's enough real volume to draw the line. |

---

## The honest 1.0 claim

Argus 1.0 produces evidence-backed consulting deliverables with a
cross-family verification layer that, on the real-claim gate, never
stamped an unsupported claim "supported" and caught every unsupported
one — at the cost of over-flagging, so a human reviews before a client
sees anything. It is 1.0 because **a real firm uses it**, within these
documented bounds — not because everything imaginable is built. Whether
the pilot is *successful* is the retro's call, not this document's.
