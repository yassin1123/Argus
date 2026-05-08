"""Companies House retriever tests (Phase 1 / Week 4 / Day 4).

Three hermetic tests + one env-gated integration canary:

  - test_resolve_tesco — mocked CH search/profile API; asserts the
    company-number resolution path.
  - test_pdf_parser_finds_canonical_sections — synthesises a UK-shaped
    annual-report PDF in-memory via PyMuPDF and asserts the parser
    detects at least 4 canonical sections.
  - test_ingest_writes_ch_filing_chunks — mocks client + embeddings +
    DB write; asserts source_type='ch_filing' + metadata shape.
  - test_real_tesco_ingestion (env-gated) — full live ingest of Tesco's
    most recent accounts when ``ARGUS_RUN_CH_INTEGRATION=1`` is set.
"""

from __future__ import annotations

import io
import json
import os
from typing import Any

import pytest

from core.retrievers.companies_house.client import CompaniesHouseClient, _pad_company_number
from core.retrievers.companies_house import (
    CHCompanyInfo,
    CHFiling,
)
from core.retrievers.companies_house import ingest as ingest_module
from core.retrievers.companies_house.parser import parse_pdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_uk_annual_report_pdf() -> bytes:
    """Synthesise a multi-page PDF with canonical UK annual-accounts headings.

    Used by the parser test so we don't need to ship a real Tesco PDF.
    PyMuPDF's PDF synthesis is straightforward — we render plain-text
    pages with a heading at the top followed by paragraph filler.
    """
    import fitz

    pages = [
        (
            "Strategic Report\n\n"
            "The Group delivered another year of strong performance, with "
            "Group sales of £61.5bn up 4.4% on a like-for-like basis. UK "
            "grocery market share strengthened to 27.6%, supported by "
            "ongoing investment in price competitiveness and the rollout of "
            "Clubcard Prices to over 8,000 lines. Adjusted operating profit "
            "rose 12.8% to £2.83bn driven by margin expansion in UK Retail "
            "and continued cost discipline. " * 6
        ),
        (
            "Directors' Report\n\n"
            "The Directors present their report and the audited financial "
            "statements for the 52 weeks ended 24 February 2024. The "
            "principal activity of the Group continues to be the operation "
            "of stores, online grocery delivery, financial services and "
            "wholesale distribution. " * 6
        ),
        (
            "Independent Auditor's Report\n\n"
            "In our opinion, the consolidated financial statements give a "
            "true and fair view of the state of the Group's affairs as at "
            "24 February 2024 and of its profit for the period then ended. "
            "We have audited the financial statements which comprise the "
            "consolidated income statement, the consolidated balance sheet, "
            "and the related notes 1 to 38. " * 6
        ),
        (
            "Income Statement\n\n"
            "Revenue from continuing operations increased to £61,475m "
            "(2023: £58,953m). Operating profit before exceptional items "
            "was £2,830m (2023: £2,508m). Profit after taxation was "
            "£2,070m (2023: £882m). Basic earnings per share were 28.45p "
            "(2023: 11.48p). " * 6
        ),
        (
            "Balance Sheet\n\n"
            "Total assets at 24 February 2024 were £42,860m (2023: "
            "£42,131m), reflecting capital investment in the UK store "
            "estate and growth in lease right-of-use assets. Total "
            "liabilities were £33,109m (2023: £33,415m). Net assets were "
            "£9,751m (2023: £8,716m). " * 6
        ),
        (
            "Notes to the Financial Statements\n\n"
            "Note 1 — Basis of preparation. The consolidated financial "
            "statements have been prepared in accordance with UK-adopted "
            "international accounting standards and with the requirements "
            "of the Companies Act 2006 as applicable to companies "
            "reporting under those standards. " * 6
        ),
    ]

    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((50, 50), body, fontsize=10)
    out = doc.tobytes()
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Test 1 — resolve by name → company number
# ---------------------------------------------------------------------------


async def test_resolve_tesco(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock /search/companies and /company/{number}; verify the path."""
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/search/companies?q=Tesco&items_per_page=10"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "company_number": "445790",  # un-padded — client must zero-pad
                            "title": "TESCO PLC",
                            "company_status": "active",
                        },
                        {
                            "company_number": "12345678",
                            "title": "TESCO HOLDINGS LIMITED",
                            "company_status": "dissolved",
                        },
                    ]
                },
            )
        if "/company/00445790" in url:
            return httpx.Response(
                200,
                json={
                    "company_number": "00445790",
                    "company_name": "TESCO PLC",
                    "company_status": "active",
                },
            )
        return httpx.Response(404, text=f"unmocked {url}")

    transport = httpx.MockTransport(_handler)
    async with CompaniesHouseClient(api_key="dummy", transport=transport) as ch:
        info = await ch.resolve_company("Tesco")

    assert isinstance(info, CHCompanyInfo)
    assert info.company_number == "00445790"  # zero-padded
    assert info.company_name == "TESCO PLC"
    assert info.company_status == "active"


def test_pad_company_number_handles_short_input() -> None:
    assert _pad_company_number("445790") == "00445790"
    assert _pad_company_number("00445790") == "00445790"
    assert _pad_company_number("SC123456") == "SC123456"


# ---------------------------------------------------------------------------
# Test 2 — PDF parser finds canonical sections
# ---------------------------------------------------------------------------


def test_pdf_parser_finds_canonical_sections() -> None:
    pdf_bytes = _build_uk_annual_report_pdf()
    sections = parse_pdf(pdf_bytes)
    assert sections, "parser returned no sections"
    item_ids = [s.item_id for s in sections]
    # The synthetic fixture has 6 canonical headings; assert ≥4 detected
    # so the test passes even if the regex is conservative.
    detected_canonical = [s for s in sections if s.item_id != "UNKNOWN"]
    assert len(detected_canonical) >= 4, (
        f"expected ≥4 canonical sections; got {item_ids}"
    )
    # Spot-check that key sections landed.
    assert "strategic_report" in item_ids
    assert "income_statement" in item_ids
    assert "balance_sheet" in item_ids


def test_pdf_parser_falls_back_to_unknown_for_micro_account() -> None:
    """Day 4 surface signal: small companies file PDFs with no canonical
    section headings. Parser should emit a single UNKNOWN section, not
    crash.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (50, 50),
        "MICRO-ENTITY ACCOUNTS\n\n"
        "Profit and loss account: Turnover £45,200. Cost of sales £30,100. "
        "Net profit £15,100. The director acknowledges responsibility for "
        "the preparation of the annual accounts in accordance with the "
        "Companies Act 2006. ",
        fontsize=10,
    )
    body = doc.tobytes()
    doc.close()
    sections = parse_pdf(body)
    # The "Profit and loss account" line matches our income-statement regex
    # but is the only canonical section, so the parser emits UNKNOWN-only.
    assert sections
    assert sections[0].item_id == "UNKNOWN"


def test_pdf_parser_returns_empty_for_empty_bytes() -> None:
    assert parse_pdf(b"") == []


# ---------------------------------------------------------------------------
# Test 3 — ingest writes ch_filing chunks (fully mocked)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    async def _stub(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    monkeypatch.setattr(ingest_module, "embed_texts", _stub)


@pytest.fixture
def stub_db(monkeypatch: pytest.MonkeyPatch) -> dict:
    state: dict[str, Any] = {"inserts": [], "ingested_keys": set()}

    async def _stub_already_ingested(company_number: str, transaction_id: str) -> bool:
        return (company_number, transaction_id) in state["ingested_keys"]

    async def _stub_insert(*, session_id, blob_id, source_file_id, source_type,
                            source_filename, source_url, trust_level, rows):
        state["inserts"].append(
            {
                "session_id": session_id,
                "source_type": source_type,
                "trust_level": trust_level,
                "source_url": source_url,
                "source_filename": source_filename,
                "rows": rows,
            }
        )
        for r in rows:
            md = r["metadata"]
            state["ingested_keys"].add((md["company_number"], md["transaction_id"]))
        return [f"id-{i}" for i in range(len(rows))]

    monkeypatch.setattr(ingest_module, "_transaction_already_ingested", _stub_already_ingested)
    monkeypatch.setattr(ingest_module, "insert_chunks", _stub_insert)
    return state


class _StubCHClient:
    """Minimal stand-in for CompaniesHouseClient — lets the ingest test
    avoid spinning up an httpx MockTransport per call.
    """

    def __init__(self, *, info: CHCompanyInfo, filings: list[CHFiling], pdf: bytes) -> None:
        self._info = info
        self._filings = filings
        self._pdf = pdf

    async def __aenter__(self) -> "_StubCHClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def close(self) -> None:
        return None

    async def resolve_company(self, name_or_number: str) -> CHCompanyInfo:
        return self._info

    async def get_filings(self, company_number, *, categories=None, items_per_page=35):
        return list(self._filings)

    async def fetch_document(self, filing: CHFiling) -> bytes:
        return self._pdf


async def test_ingest_writes_ch_filing_chunks(
    stub_embed,  # noqa: ARG001
    stub_db: dict,
) -> None:
    pdf = _build_uk_annual_report_pdf()
    client = _StubCHClient(
        info=CHCompanyInfo(
            company_number="00445790",
            company_name="TESCO PLC",
            company_status="active",
        ),
        filings=[
            CHFiling(
                transaction_id="TX-TESCO-2024",
                category="accounts",
                description="accounts-with-accounts-type-group",
                filing_date="2024-06-12",
                period_end="2024-02-24",
                document_id="abc-doc-id-2024",
            )
        ],
        pdf=pdf,
    )
    from core.retrievers.companies_house.ingest import ingest_company

    result = await ingest_company(
        company_number="00445790",
        limit=1,
        client=client,  # type: ignore[arg-type]
    )

    assert result.errors == []
    assert result.filings_ingested == 1
    assert result.chunks_written > 0

    # We made one insert_chunks call per filing.
    assert len(stub_db["inserts"]) == 1
    call = stub_db["inserts"][0]
    assert call["source_type"] == "ch_filing"
    assert call["trust_level"] == "firm_vetted"
    assert call["source_url"].startswith(
        "https://find-and-update.company-information.service.gov.uk/company/00445790/"
    )

    sample = call["rows"][0]
    md = sample["metadata"]
    for key in (
        "company_number",
        "company_name",
        "transaction_id",
        "category",
        "filing_date",
        "section_canonical_name",
        "item_id",
    ):
        assert key in md, f"missing metadata key {key!r}"
    assert md["company_number"] == "00445790"
    assert md["transaction_id"] == "TX-TESCO-2024"
    assert md["category"] == "accounts"


async def test_ingest_idempotent(
    stub_embed,  # noqa: ARG001
    stub_db: dict,
) -> None:
    """Re-running the same (company_number, transaction_id) is a no-op."""
    pdf = _build_uk_annual_report_pdf()
    client = _StubCHClient(
        info=CHCompanyInfo("00445790", "TESCO PLC", "active"),
        filings=[
            CHFiling(
                transaction_id="TX-TESCO-2024-IDEM",
                category="accounts",
                description="accounts-with-accounts-type-group",
                filing_date="2024-06-12",
                period_end="2024-02-24",
                document_id="doc-idem",
            )
        ],
        pdf=pdf,
    )
    from core.retrievers.companies_house.ingest import ingest_company

    first = await ingest_company(company_number="00445790", limit=1, client=client)  # type: ignore[arg-type]
    second = await ingest_company(company_number="00445790", limit=1, client=client)  # type: ignore[arg-type]

    assert first.filings_ingested == 1
    assert second.filings_ingested == 0
    assert second.filings_skipped_idempotent == 1


# ---------------------------------------------------------------------------
# Test 4 — env-gated integration canary
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("ARGUS_RUN_CH_INTEGRATION") != "1",
    reason="set ARGUS_RUN_CH_INTEGRATION=1 to run live Companies House ingest",
)
async def test_real_tesco_ingestion() -> None:
    """Live ingestion of Tesco's most recent accounts. Cleans up after."""
    from core.retrievers.companies_house.ingest import ingest_company
    from db.connection import acquire, close_db, init_db

    await init_db()
    try:
        result = await ingest_company(company_number="00445790", limit=1)
        assert result.errors == [] or all("idempotent" in e.lower() for e in result.errors)
        if result.filings_ingested > 0:
            assert result.chunks_written >= 5
            async with acquire() as conn:
                await conn.execute(
                    """
                    DELETE FROM chunks
                    WHERE source_type = 'ch_filing'
                      AND metadata->>'company_number' = $1
                    """,
                    "00445790",
                )
    finally:
        await close_db()
