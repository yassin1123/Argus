# Valuation Methodology (Firm House View)

This methodology codifies the firm's house approach to valuing
private and recently-public targets across diligence, fairness
opinion, and growth-strategy contexts. It is fully synthetic —
written for fixture use only — but reflects the actual triangulation
the firm uses when a number has to land on a partner's desk.

## Core principle: triangulate, don't single-point

The firm's discipline is that no valuation work product leaves the
office with a single-point number. Every valuation deliverable
triangulates across three methods — discounted cash flow, public
trading comparables, and precedent transactions — and the
recommended range is the intersection, not an average.

A valuation that depends on one method is fragile. A valuation
that depends on three converging methods is defensible.

## DCF approach

The DCF construction the firm prefers is **two-stage explicit-plus-
terminal** with a 5-year explicit forecast and a Gordon-growth
terminal. We do not use the H-model, three-stage, or fade-rate
constructs except in regulated-utility contexts.

The five forecast years are built bottom-up from operational
drivers, not top-down from a revenue CAGR:

- **Revenue** is forecast by line of business, by channel, or by
  customer cohort depending on the business shape. A revenue
  forecast that says "revenue grows at 12% per year" without
  decomposition is a placeholder, not a forecast.
- **Gross margin** is forecast as a rate path, with explicit
  scenarios for input cost movement. Flat gross margin is a
  default assumption only when the diligence shows explicit
  contractual or structural protection.
- **Opex** is forecast in three buckets: variable, semi-fixed,
  fixed. The buyer should be able to see operating leverage in
  the forecast or the forecast is wrong.
- **Working capital** is forecast as days of revenue / cost of
  goods, not as a percentage. Days reveals operational reality
  in a way the percentage does not.
- **Capex** is forecast as maintenance capex plus growth capex,
  with growth capex tied to the operational driver the growth
  is funding (new stores, new capacity, new product launches).

WACC is built up:

- Risk-free rate: the 10-year sovereign yield in the target's
  primary cash-flow currency, on the valuation date, not the
  trailing 12-month average.
- Equity risk premium: 5.5% for developed markets as the firm's
  current house view, with a 1-2% additional premium for
  small-cap targets (sub-£500m EV).
- Beta: re-levered from a peer-group asset beta, with the
  target's own capital structure applied. We do not use raw
  observed equity beta for sub-scale targets — the regression
  noise dominates the signal.
- Cost of debt: the marginal cost the buyer would actually face,
  not the target's existing rate. A target's existing 4% coupon
  on debt issued in 2021 is not the buyer's cost of debt today.

Terminal growth is capped at long-run nominal GDP for the target's
primary geography (~3% for UK / Western Europe, ~4% for the US as
of 2026). Terminal multiples used as a sanity check on the implied
exit EV/EBITDA — anything above one turn over current trading
multiples needs a written defence.

## Public trading comparables

The discipline on the comp set:

- **At least 6 comparables**, typically 8-12, with the rationale
  for each comp and the rationale for each rejected candidate
  documented. A comp set that's curated to support the answer
  is not analysis.
- **Size-band adjustment**: comps materially larger than the
  target trade at premium multiples for liquidity and scale
  reasons that don't transfer to a smaller target. The firm
  applies a 10-25% size discount when the comp median market
  cap exceeds 5x the target's expected EV.
- **Growth-band adjustment**: when the target's expected revenue
  CAGR differs from the comp median by more than 5pp, we
  regress the comp set's EV/Revenue multiple on growth and
  apply the implied delta.
- **Multiples used**: EV/EBITDA is the default; EV/Revenue for
  high-growth low-profit targets where EBITDA is not yet
  representative; EV/EBIT for asset-heavy targets where D&A
  treatment is non-comparable. P/E is rarely used because the
  capital structure of the target and the comps differ.

## Precedent transactions

The transaction set is filtered tightly:

- Deals from the **last 24 months** in the same sector, same
  geography, similar size band. Deals older than 24 months are
  reference, not anchor.
- Strategic vs sponsor-led deals are tracked separately. The
  sponsor median is typically 1-2 turns lower than the strategic
  median; using a blended median over-prices the target if the
  buyer is a sponsor.
- Deal multiples are sourced from the announcement, not the
  rumoured-pre-announcement chatter. Press-leaked multiples are
  routinely 1-2 turns higher than the actual transaction terms.

## Sensitivity analysis

Every DCF the firm produces is delivered with a sensitivity grid
across at least three pairs of assumptions:

- WACC vs terminal growth (the standard exam-question pair)
- Revenue CAGR vs gross margin (the operational pair)
- Working capital days vs growth capex (the cash conversion pair)

The sensitivity grid is presented as a heat-map in the partner
deck, with the recommended bid range overlaid as a region rather
than a point. Decision quality in valuation work comes from
helping the buyer see the *shape* of the value, not just the
central estimate.

## Output

The valuation work product is:

- **One-page recommended bid range** with the high, mid, and low
  point and the assumption that drives each.
- **Three-page triangulation summary** showing the DCF, comps,
  and precedent ranges side by side and explaining the
  reconciliation where they disagree.
- **The full model** with the assumption flex sheet visible,
  delivered to the buyer's deal team.

A valuation deliverable without the assumption flex sheet exposed
to the buyer is non-compliant with the firm's standards — the
buyer must be able to interrogate every input.
