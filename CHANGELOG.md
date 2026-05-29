# Changelog

All notable changes to Argus. This project's versioning is earned, not
nominal: **v1.0.0 ships because a real firm is using it in a live pilot**,
within documented bounds — see `docs/v1.0/scope.md`.

## [1.0.0] — 2026-05 — first pilot

The arc from nothing to a real firm running real engagements.

### Headline capabilities
- **Verification spine.** Claim-level source binding; cross-family
  verification (Anthropic synthesis × OpenAI gpt-4o judge) enforced at
  boot; a three-signal NLI ensemble (LLM judge + DeBERTa-v3 cross-encoder
  + lexical/numeric overlap) that only downgrades.
- **Six-artifact deliverable suite** from one verified claim base: memo,
  one-pager, deck (PPTX), Excel model, client email, interview guide —
  every factual claim traceable to a source.
- **Firm knowledge + layered modes.** Per-firm library (firm-scoped,
  never cross-leaking), built-in + per-firm consulting modes, structured
  frameworks (2×2, Porter's, Value Chain), firm branding on every output.
- **Full collaboration layer.** Review workflow with lock-on-approval,
  anchored comments + @-mentions, per-section ownership + tasks +
  my-work queue, notifications, version history with diff + restore.
- **Observability.** Structured logs + traces, metrics, cost ledger,
  admin dashboard, live-pilot watch view + operator alerting.
- **Four enterprise pillars.** Tenant isolation (cross-firm → 404),
  data retention + hard deletion, append-only audit + content-free
  export, cost governance (budgets + ceilings + rate limits + alerts).
- **Production deploy.** Managed-Postgres config (encryption-at-rest +
  TLS), automatic TLS proxy, secrets via env/secret-store, idempotent
  migration runner, fail-loud production boot guard, pre-flight smoke
  check, backup/restore.

### The measured verification guarantee
- Real-claim calibration gate (W24/D1): **0% false-positives-on-supported**
  and **100% recall-on-insufficient** on 61 human-labelled real claims
  through the cross-family verifier. Verdict: **GREEN**.
- Posture: **"verified (conservative)"** — the verifier never wrongly
  blesses an unsupported claim, but it over-flags (recall-on-supported
  ~27%), so a human reviews flagged claims before delivery.

### Known limitations (honest)
- The verifier is **conservative** — expect more "needs review" flags
  than strictly necessary. That's the safe direction, not a defect.
- The true **edit rate** (how much consultants rewrite drafts) is being
  measured live in the pilot; it's the first real product-fit signal.
- **Deferred to post-1.0** (named in `docs/v1.0/scope.md`): SSO/SAML,
  application-level field encryption, external pen-test/SOC 2, Companies
  House OCR, multi-instance/HA, notification digests + push, element-level
  artifact commenting, text-range re-anchoring, verifier-recall
  improvement.

### Pilot status
Launched and running with one boutique firm. **"Launched and running" is
not "successful"** — that's the retrospective's call, informed by the
live edit-rate, claim-feedback-agreement, and artifact-rating signals.

---

_Phase-by-phase development history (Phases 1–5, Weeks 1–25) lives in the
`docs/eval/` wrap-ups and the git history._
