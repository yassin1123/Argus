# Verifier Report — Germany vs France

> What the verifier agent did with the analyst's claims. Every claim is re-checked against the evidence catalog; verdicts and entailment scores are persisted in `claim_support_rows`.

**Overall:** sufficient · **8 of 9** claims supported, **1** weak, 0 unsupported, 0 overstates

---

## Per-claim verdicts

### c1 — Germany's B2B SaaS market is approximately 1.6× the size of France's.

| Field | Value |
|-------|-------|
| Verdict | **supported** ✓ |
| Support type | direct_quote |
| Entailment score | 0.91 |
| Evidence ids | e1, e2 |
| Verifier note | Multiple corroborating sources for relative market size. |

**Evidence backing this claim:**
- *e1 — Bitkom, German Software Market Outlook 2024 (high confidence):* "Germany's B2B SaaS market reached approximately €18.4B in 2024, the largest in continental Europe and roughly 1.6× the size of France."
- *e2 — Numeum, French SaaS Market Report 2024 (high confidence):* "France posted 22% YoY growth in B2B SaaS spend in 2024…"

---

### c2 — Mittelstand B2B SaaS net revenue retention (117%) is structurally higher than French mid-market (109%).

| Field | Value |
|-------|-------|
| Verdict | **supported** ✓ |
| Support type | direct_quote |
| Entailment score | 0.86 |
| Evidence ids | e9 |
| Verifier note | NRR figure consistent with adjacent benchmarks. |

**Evidence backing this claim:**
- *e9 — OpenView, European NRR Benchmarks 2024 (medium confidence):* "Net revenue retention in German Mittelstand B2B SaaS averages 117% vs 109% in French mid-market — slow to land but stickier."

---

### c3 — Sequenced single-country entry produces 2.3× the qualified pipeline at 12-headcount caps compared to parallel entry.

| Field | Value |
|-------|-------|
| Verdict | **supported** ✓ |
| Support type | paraphrase |
| Entailment score | 0.82 |
| Evidence ids | e8 |
| Verifier note | Bessemer dataset cited; n=47 acceptable for directional claim. |

**Evidence backing this claim:**
- *e8 — Bessemer, European Expansion Playbook 2024 (medium confidence):* "At 12-headcount caps, sequenced entry to a single anchor market produced 2.3× the qualified pipeline in 18 months vs split parallel entries (n=47 expansions)."

---

### c4 — Two-quarter pilots in target accounts reliably resolve go/no-go on full entry economics with ~80% accuracy. ⚠

| Field | Value |
|-------|-------|
| Verdict | **weak** ⚠ |
| Support type | inference |
| Entailment score | 0.58 |
| Evidence ids | e10 |
| Staleness hint | Internal pattern; n=12 cases — small sample |
| Verifier note | Inference-only support; treat 80% accuracy figure as directional. |

**Why this is flagged weak:**
- Only one piece of supporting evidence (e10 is an internal pattern flagged `is_inference=true`).
- Sample size on the supporting evidence is small (n=12).
- The 80% figure should be treated as directional, not load-bearing.

**Evidence backing this claim:**
- *e10 — Argus internal pattern library (medium confidence, **inference**):* "Two-quarter pilot programs in target accounts produced a go/no-go decision with 80%+ accuracy on full-scale entry economics in 11 of 12 cases reviewed."

> This is the kind of claim that the report's caveat banner surfaces to the reader. The recommendation does not rest solely on c4 — it's reinforced by c1–c3 — but a careful reader should know that the *quantification* of pilot reliability is weakly grounded.

---

### c5 — France grows faster (22% vs 14% YoY) and is cheaper to staff but the public-sector tailwind is hard to capture at 12 headcount.

| Field | Value |
|-------|-------|
| Verdict | **supported** ✓ |
| Support type | paraphrase |
| Entailment score | 0.84 |
| Evidence ids | e2, e3, e7 |
| Verifier note | Procurement cycle and cost figures from independent sources align. |

---

### c6 — German enterprise buyers expect in-country data residency at higher rates (68%) than French buyers (41%).

| Field | Value |
|-------|-------|
| Verdict | **supported** ✓ |
| Support type | direct_quote |
| Entailment score | 0.88 |
| Evidence ids | e5 |
| Verifier note | RFP data-residency rate sourced from IDC survey. |

**Evidence backing this claim:**
- *e5 — IDC, European Cloud Buyer Survey 2024 (medium confidence):* "German enterprise buyers more frequently require in-country data residency (68% of RFPs vs 41% in France), even where GDPR alone does not mandate it."

---

## How verdicts roll up to the trust rail

The trust rail in the workspace UI ([frontend/components/sessions/TrustRail.tsx](../../../frontend/components/sessions/TrustRail.tsx)) shows:

| Field | This case study |
|-------|------------------|
| `confidence_label` | medium-high (capped from "high" because of the weak claim) |
| `verification_overall_label` | sufficient |
| `claims_verified_hint` | "8 of 9 supported; 1 weak" |
| `unsupported_claims_count` | 1 (the weak claim is counted in the "needs review" bucket) |
| `caveats_preview` | First sentence of the report's caveats section |

---

## How verdicts get computed

1. **Analyst** emits `key_claims: [{claim_id, text, evidence_ids: [...]}]`.
2. **Verifier** receives the analyst payload + the full evidence catalog and emits `claim_assessments: [{claim_id, verdict, evidence_ids, notes}]`.
3. **`backend/core/claim_support.py`** joins analyst claims, verifier assessments, and evidence rows into `claim_support_rows` with `support_type`, `verifier_verdict`, `entailment_score`, `weak_or_unsupported`.
4. **`backend/core/contradiction_policy.py`** caps the report's `confidence_level` if the verifier flagged contradictions or weak claims.
5. **Trust rail DTO** ([backend/models/workspace_dto.py](../../../backend/models/workspace_dto.py)) computes display labels server-side; the UI never derives them from raw rows.

---

## Strict mode

Set `ARGUS_STRICT_NO_INFERENCE_ONLY=1` in `.env` and the analyst would be **forbidden** from synthesizing a claim where every supporting evidence object has `is_inference=true`. Under strict mode, claim c4 would have triggered a pipeline revision rather than a weak verdict — the analyst would have to either cite non-inference evidence or drop the claim.

That's a deliberate tradeoff: weak verdicts let the report be useful while flagging fragile claims; strict mode forces the report to never lean on inference at all. Choose per engagement.
