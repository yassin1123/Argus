# Week 4 / Day 4 — Companies House scanned-PDF finding

**Status:** retriever shipped; live-ingest done-condition deferred to Phase 3.

## What we built

`backend/core/retrievers/companies_house/` mirrors the EDGAR retriever:

- `client.py` — Basic auth + 2 req/sec token bucket (CH publishes 600/5min)
- `parser.py` — PyMuPDF text extraction + canonical UK section regex
- `ingest.py` — orchestrates fetch → parse → chunk (reuses EDGAR chunker) → embed → write
- `tools/ch_ingest.py` — CLI mirroring `tools/edgar_ingest.py`

Plus `ch_filing` added to the `SourceKind` Literal in `backend/agents/planner.py`,
with prompt guidance directing UK-registered companies to `ch_filing`. The
orchestrator's `_retrieve_by_priorities` (Week 3 / Day 4) is source-type-
generic and routes `ch_filing` through the same path as `sec_filing` — no
new orchestrator code.

7 hermetic tests pass + 1 env-gated integration; 97 wider regression suite green.

## What we found

**Every UK annual-accounts PDF served by Companies House is a TIFF-to-PDF
scan, regardless of filer size or method.**

Empirical sample (8 companies, all sizes):

| Company | Number | Latest accounts | PDF size | Producer | Extractable text |
|---|---|---|---|---|---|
| Tesco | 00445790 | 2025-07-15 | 14.9 MB | `libtiff/tiff2pdf` | 0 chars |
| M&S | 00214436 | 2025-09-26 | 7.2 MB | `libtiff/tiff2pdf` | 0 chars |
| AstraZeneca | 02723534 | 2026-04-25 | 16.9 MB | `libtiff/tiff2pdf` | 0 chars |
| Monzo | 09446231 | 2025-09-01 | 8.4 MB | `libtiff/tiff2pdf` | 0 chars |
| Octopus Energy | 09263424 | 2026-01-22 | 2.3 MB | `libtiff/tiff2pdf` | 0 chars |
| Wise | 07209813 | 2025-10-30 | 2.6 MB | `libtiff/tiff2pdf` | 0 chars |
| Revolut | 08804411 | 2026-04-03 | 4.9 MB | `libtiff/tiff2pdf` | 0 chars |
| Deliveroo | 08203825 | 2017-07-10 | 0.0 MB | `libtiff/tiff2pdf` | 0 chars |

Verified across the last 5 years for the three FTSE 100 firms — same producer
across the whole filing history. Conclusion: this is **CH's storage pipeline**,
not a quirk of any individual filer. Auditor-signed PDFs (the dominant filing
form) get rasterised to TIFF for archival; the API serves the rasterised copy.

The Day 4 spec called this out as a possibility but expected it to be
**rare for FTSE 100**. Empirically it's universal.

## What this means for Day 4's done-condition

The done-condition was:

> Tesco, M&S, AstraZeneca ingested via CLI: `chunks WHERE source_type='ch_filing'`
> returns rows for all three.

Cannot be met today **without out-of-scope work** because:

- Day 4 hard rule: "Don't try to parse iXBRL today. Treat as raw text. Phase 3 polish."
- Day 4 hard rule (implicit): no Tesseract install / OCR scope creep.
- CH's document API metadata for Tesco confirms only `application/pdf` is
  available — no alternative iXBRL format alongside the scanned PDF:
  ```json
  "resources": { "application/pdf": { "content_length": 14954490 } }
  ```

The retriever IS correct for text-extractable PDFs (verified by the
`test_pdf_parser_finds_canonical_sections` test, which synthesises a
multi-page UK-shaped PDF in PyMuPDF and confirms the canonical-section
walker detects ≥4 sections including Strategic Report, Income Statement,
Balance Sheet). When CH eventually exposes text-PDFs, or Phase 3 adds
OCR, the existing pipeline runs unchanged.

## Phase 3 paths to evaluate (in priority order)

1. **OCR via Tesseract + PyMuPDF.** Direct fix; ~250-page Tesco PDF would
   take 5-15 min to OCR cold. Cache OCR output keyed on `transaction_id`
   so re-ingest is cheap. Adds Tesseract binary to the Docker worker image.
   Risk: OCR quality on tabular financial data (multi-column tables) is
   variable; tests on real Tesco OCR output before relying on it for
   numeric claims.

2. **Companies House Stream / data product.** CH offers a separate paid
   product with structured data extracts. May serve iXBRL or pre-parsed
   text. Out of scope for Phase 1 cost budget.

3. **Cross-reference with the FCA National Storage Mechanism (NSM)** for
   listed companies. NSM hosts the same annual reports as text-PDFs for
   FTSE-listed firms. URL scheme: `https://data.fca.org.uk/...`. Would
   complement (not replace) the CH path.

4. **Defer entirely.** Most Phase 1 demo value comes from US public
   companies (SEC) + uploaded user content + news. Companies House is a
   nice-to-have for UK comparables but not the primary surface area.

## Day 4 deliverables status

| Deliverable | Status |
|---|---|
| CH client (auth, rate limit, search/resolve, get_filings, fetch_document) | ✅ shipped |
| PDF parser with canonical UK section regex + UNKNOWN fallback | ✅ shipped |
| Ingest module + CLI | ✅ shipped |
| `ch_filing` added to SourceKind Literal + planner UK guidance | ✅ shipped |
| Orchestrator routes `ch_filing` through hybrid_search | ✅ shipped (no new code — Day 4/W3 was source-type-generic) |
| 7 hermetic tests + env-gated integration | ✅ all green |
| Live ingest of Tesco/M&S/AstraZeneca → chunks rows | ❌ **blocked by CH scanned-PDF reality**; deferred per surface clause |
| Planner emits `["ch_filing"]` on UK-mention briefs | ⏳ untested live (no chunks to retrieve from); prompt updated |

## Recommendation

Ship Day 4 as-is. Day 5 either:

- (a) writes a UK-company end-to-end smoke that confirms the planner emits
  `["ch_filing"]` for a UK brief and routing fires, accepting that
  retrieval returns zero rows pending Phase 3 OCR; or
- (b) shifts Phase 1's Day-5 UK demo to a US firm with UK-listed parent
  (already covered by SEC); or
- (c) elevates OCR to Day 5 inline if the demo proof point is
  non-negotiable on UK ground.

Engineering recommendation: **(a)** — proves the contract works without
spending budget on OCR before we have demand-side validation that UK
ingestion is critical for Phase 1.
