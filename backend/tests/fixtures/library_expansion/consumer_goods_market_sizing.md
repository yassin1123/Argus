# Consumer Goods Market Sizing — Methodology + UK Reference Pack

## When to reach for this pack

This pack is the firm-internal reference for sizing UK consumer-goods
markets in growth-strategy and M&A diligence engagements where the
target sells branded or own-label physical product through grocery,
convenience, online, or specialist retail channels. Categories explicitly
in scope: ambient food and drink, household and personal care, beauty
and OTC health, pet food and accessories, soft drinks, and adjacent
premium impulse categories.

We deliberately exclude alcohol (separate framework), tobacco, vape
and nicotine products, fresh produce (separate seasonality model),
and big-ticket durables.

## Sizing layers

The methodology operates in four layers:

1. **Category total addressable market (TAM)** — retail-sales value of
   the category in the geography. Source priority: Nielsen / IRI /
   Circana-equivalent panel data, ONS retail-sales index for top-down
   sanity, AC Nielsen-equivalent shopper panels for share-of-wallet.
2. **Serviceable addressable market (SAM)** — the slice of TAM the
   target's distribution footprint can actually reach. Adjustments
   typically remove channels the target doesn't currently sell to
   (e.g. discounters, foodservice, online pureplay) and price tiers
   the product can't price-credibly compete in.
3. **Serviceable obtainable market (SOM)** — realistic 3-year share
   capture given retailer-listing realities, advertising-to-sales
   ratio constraints, and competitive response.
4. **Volume-to-value bridge** — units, average selling price, mix
   shift, promotional depth, and net-revenue management. Each level
   reconciles to the next; reconciliation gaps flag a methodology
   problem.

## Channel-mix reference (UK, current synthetic snapshot)

| Channel              | Share of grocery value | Share of own-label | Growth (LFL) |
|----------------------|------------------------|--------------------|--------------|
| Tesco                | 27.5%                  | 51%                | +1.8%        |
| Sainsbury's          | 14.8%                  | 49%                | +2.1%        |
| Asda                 | 13.1%                  | 56%                | -0.4%        |
| Morrisons            | 8.4%                   | 47%                | -1.2%        |
| Aldi                 | 10.8%                  | 88%                | +6.7%        |
| Lidl                 | 8.0%                   | 83%                | +5.4%        |
| Waitrose             | 4.6%                   | 36%                | +0.6%        |
| Convenience / symbol | 7.5%                   | 22%                | +0.9%        |
| Online pureplay      | 3.4%                   | 28%                | +4.1%        |
| Specialist / other   | 1.9%                   | n/a                | +1.5%        |

(Synthetic — refresh quarterly against current Circana / Nielsen
data when re-running the engagement.)

## Pricing architecture

Branded consumer-goods pricing typically arranges across four tiers:

- **Super-premium** — 2.0x+ category-average price; design-led,
  small-batch, sold through Waitrose and specialty.
- **Premium** — 1.3-1.7x category average; the volume segment for
  brand owners; most NPD lands here.
- **Mid-market** — 0.9-1.2x average; the most-contested tier,
  particularly against private label.
- **Value** — 0.6-0.9x average; almost entirely own-label and
  discount-channel brands; thin economics for branded entrants.

The classic strategic move in growth-strategy work for consumer goods
is "trade up the brand without abandoning the volume tier" — easier said
than done; requires distinct ranges + careful merchandising support
so the existing trade isn't trained to wait for promotion.

## Discounter pressure

The structural risk in UK consumer goods over the last decade has been
discounter share growth (Aldi + Lidl combined ~18.8% as of this
snapshot, up from ~6% in 2010). Defensive plays the firm has seen work:

1. **Premium-tier expansion** — move the volume centre of the brand
   into the £-spend-per-shopping-basket band where discounters under-index.
2. **Own-label supply to multiples + branded direct** — dual play
   that uses scale to pay back fixed costs while protecting brand
   margin.
3. **Innovation-led category expansion** — new use occasions,
   premium ingredients, format innovation — moves the brand to a
   category-adjacent space where discounters lag.
4. **Channel diversification — online + DTC** — sells the brand
   direct or via pureplay where the discounter share is structurally
   lower.

What rarely works defensively: matching discounter price points (margin
unsustainable), incremental brand investment without distribution gains
(diminishing returns), or relying on heritage alone (younger shoppers
under-index on legacy brand affinity).

## Promotional intensity benchmarks

The synthetic peer set shows the following typical promotional intensity
by tier:

- **Super-premium:** 8-14% of volume on deal
- **Premium:** 22-32% on deal
- **Mid-market:** 38-48% on deal
- **Value / own-label:** <5% on deal

Engagements that recommend brand premiumisation should bake an explicit
promotional-intensity reduction into the financial model; otherwise
the gross-margin uplift is illusory.

## Quick sizing formula

For a growth-strategy "should we enter category X in the UK?" question,
the sizing pass is:

```
SAM = TAM × (channels_reached / channels_total) × (price_tier_share)
SOM_yr1 = SAM × min(0.5%, marketing_spend / category_marketing_spend × 1.5)
SOM_yr3 = SAM × 1.5-3.0% depending on channel intensity + distribution
```

These coefficients aren't from a single source — they're calibrated on
the firm's own track record. Use them as a sense-check on whatever
bottom-up numbers the analyst surfaces; flag any pitch deck that claims
SOM ≥5% inside 3 years unless the target already has retailer
commitments in writing.

## Cross-references

- **UK retail competitive landscape** — separate firm-library doc
  covering grocery format dynamics + retailer P&Ls.
- **Comparable transactions database** — for sector M&A multiples.
- **GDPR / marketing-data brief** — when DTC channel is in scope.

Internal note: every number here is synthetic. Refresh against the
current panel data before citing in a client-facing memo.
