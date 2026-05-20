# Sample workspace walkthrough — "Meridian Advisory"

A 10-minute path through the seeded sample workspace. Use this to
onboard a new teammate, run a customer demo, or sanity-check the
end-to-end product surface after a stack change.

## 1 — Seed the workspace

From the repo root (Docker stack up):

```
python tools/seed_sample_workspace.py
```

The seeder is idempotent — re-run any time. Add `--reset` to drop
the existing Meridian sessions and start fresh; add `--skip-artifacts`
to skip the bundle regeneration if you only changed library content
or user metadata.

Expected output (abridged):

```
firm: Meridian Advisory  id=<uuid>
users: 3 provisioned
library: <N> new chunks ingested (existing rows dedup-skipped)
engagement: restoring 'Kestrel Logistics — M&A diligence' ...
  artifacts: 7/10 ready  (3 PDFs skipped on hosts without WeasyPrint)
engagement: restoring 'Halcyon Health Group — UK SaaS expansion' ...
  artifacts: 7/10 ready

Sample workspace ready — firm slug: meridian-advisory
```

## 2 — Log in as the partner

URL: `http://localhost:3000/login` (or your local frontend port).

  - Email: `helena.voss@meridian.invalid`
  - Password: `MeridianSample!2026`

After login Helena lands on the engagement list. Two engagements are
visible: `Kestrel Logistics — M&A diligence` and `Halcyon Health Group
— UK SaaS expansion`.

## 3 — Open the M&A engagement (Kestrel Logistics)

Walk-through items, in order:

1. **Memo first.** The MemoEditor opens to the writer's payload.
   Hover any claim-bearing sentence — the citation chip surfaces the
   source quote. The recommendation reads:
   `PROCEED WITH CONDITIONS at a £215–£235m enterprise value range,
   anchored to a base case of £225m (EV/EBITDA 10.7x) subject to
   confirmation of the top-three customer contract block.`

2. **Section deepening history.** Open the W9 deepening panel. Two
   completed deepening runs are visible:
   - Walk-away triggers (pressure-tested + tightened).
   - Synergy dis-synergies (quantified against the comparable
     transactions database).

3. **Export the 1-pager.** Top bar → `Export ▾` → `1-pager (HTML)`.
   Opens in a new tab. Verify: firm-branded header (Meridian's
   `#1F3A5F` primary colour), recommendation panel colour-coded
   amber ("PROCEED WITH CONDITIONS"), top-3 reasons + risks, M&A
   valuation row showing the £215–£235m triple, numbered citation
   chips with `data-claim-id` markers.

4. **Export the deck.** `Export ▾` → `Deck (PPTX)`. Open the file.
   11 slides: title → exec_summary → target_overview (Kestrel) →
   financial_profile (revenue + EBITDA trajectories) → valuation_range
   (the £215/225/235m triple) → 2x2 (deal complexity vs strategic
   fit) → risks_matrix → integration_plan → recommendation →
   next_steps → sources.

5. **Export the Excel model.** `Export ▾` → manual `excel_model/xlsx`
   trigger via the artifacts panel (or from the same `Export ▾`
   dropdown). 10 sheets in visual order: Cover → Summary → Assumptions
   → Revenue Build → Cost Build → Working Capital → DCF → Comparables
   → Sensitivity → Synergies. The DCF Enterprise Value cell carries a
   live formula (`=SUM(B14:F14)+F20`); changing WACC on Assumptions
   re-computes every DCF discount factor. Citation comments are
   present on payload-derived cells; hover for the `[claim_id]`
   breadcrumb.

6. **Export the cover email.** `Export ▾` → `Cover email (MD / HTML / PDF)`.
   The markdown version opens for paste-into-mail-client; the HTML
   and PDF land in the artifacts panel. Body word count is ~210
   words (≤250 cap); the attachment bundle lists the previously-
   generated artifacts (1-pager, deck, Excel) with their detail
   strings ("1-page", "11 slides", "10 sheets …").

7. **Export the interview guide.** Same dropdown path. The MD version
   opens as the default; the PDF is multi-page (6 pages on this
   payload) with running header (`Meridian Advisory — Kestrel
   Logistics — M&A diligence`) and a per-page footer. Section A
   pulls from the analyst's gap_report (or renders the honest "no
   critical evidence gaps" line); Section B is the recommendation
   pressure-test with `[claim_id: …]` markers in the markdown;
   Section C is the M&A integration / synergy / walk-away deep-dive.

## 4 — Open the growth engagement (Halcyon Health Group)

This engagement demonstrates the W14/D1 carry-forward closure
end-to-end. The cached fixture ships a fully-populated Porter's
Five Forces block (intensity + rationale + key_drivers +
evidence_citations on each of the 5 forces).

1. **Memo.** Recommendation reads:
   `EXPAND INTO SCOTLAND via a partner-led entry into NHS Highland
   over the next 18 months.` The "Porter's Five Forces" framework
   panel renders the 5-force grid — verify each force shows non-empty
   intensity + rationale.

2. **Export the deck.** 9 slides: title → exec_summary → context →
   market_landscape → porters_five_forces_visual (the 5-force boxes,
   colour-coded by intensity: red HIGH on rivalry + new_entrant_threat,
   amber MODERATE on buyer_power, green LOW on supplier_power +
   substitute_threat) → recommendation → risks_matrix → next_steps →
   sources.

3. **Export the 1-pager.** Verify the "top competitive force" row
   shows real content (`new_entrant_threat — high intensity`) rather
   than the documented W11/D5 fallback.

4. **Export the cover email.** Body word count ~245; the recommendation
   paragraph references the strategic direction (partner-led entry
   into NHS Highland), the caveat paragraph names the top competitive
   force as the watch-item.

5. **Export the interview guide.** Section C is mode-aware — growth
   gets competitive response / channel mix / customer-behaviour
   delta / pilot design / leading-indicators questions (not the M&A
   integration deep-dive).

## 5 — Cross-engagement product surface

Once both engagements are open, demonstrate the cross-engagement
glue:

  - **Library**: `Firm Library` in the sidebar — Meridian has 6
    library items ingested via the W14/D2 hardened bulk path (UK SaaS
    primer, consumer-goods market sizing, M&A carve-out playbook,
    regulatory brief, diligence checklist, comparable transactions
    CSV). Both engagements cite these in their `sources` and
    `recommendation_claim_ids`.
  - **Email attachment-bundle awareness**: regenerate the email on
    the M&A engagement. The attachment list reflects whichever
    artifacts were generated most recently AND flags any that are
    older than the current payload as `may need refresh, generated
    N days ago` via the W13/D2 fingerprint diff.
  - **User roles**: log out and back in as
    `marcus.thorne@meridian.invalid` (senior consultant) — same
    engagements visible (firm-scoped). Engagement-membership role for
    both is `member` (not `lead`); Marcus can comment + edit memo
    but membership UI shows Helena as the lead.

## 6 — Demo carry-forwards (be honest)

  - **PDFs only render where WeasyPrint's native libs are installed.**
    On Windows dev hosts the seeder skips the 3 PDF artifacts with a
    clear `skipped_no_weasyprint` status. The Docker `argus-worker-1`
    container has the libs; for a customer demo, regenerate the
    bundle from within the worker (see W13/D5 wrap-up for the
    docker-exec recipe).
  - **The growth engagement's Porter's is hand-curated in the
    fixture**, not LLM-emitted on the W14 stack. Phase 4 closes the
    schema-enforcement gap (W14/D1 wrap-up): once that lands,
    re-running the engagement via the live LLM pipeline will produce
    the same shape. Today's seeder demonstrates the end-state.
  - **The artifacts panel may show 3 `failed` rows alongside the 7
    `ready` ones on Windows hosts.** This is the WeasyPrint
    environment gap, not an artifact-pipeline regression.

## Quick reference — credentials

| Role               | Email                              | Password               |
|--------------------|------------------------------------|------------------------|
| Partner (firm admin) | helena.voss@meridian.invalid     | MeridianSample!2026    |
| Senior consultant  | marcus.thorne@meridian.invalid     | MeridianSample!2026    |
| Junior analyst     | priya.shah@meridian.invalid        | MeridianSample!2026    |

The fixture JSON at
`backend/tests/fixtures/sample_workspace/workspace.json` is the
canonical source for credentials + branding + per-user titles.
