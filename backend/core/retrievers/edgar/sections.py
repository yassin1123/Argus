"""Canonical section taxonomies for SEC filings.

Phase 1 / Week 3 / Day 2. Each entry is
``(item_id, canonical_name, regex_patterns)`` where ``regex_patterns`` is
a list of case-insensitive regexes that are tested against the stripped
text of a heading-shaped block. Multiple patterns per item handle the
ways issuers actually format the same section across 10-K vintages
("ITEM 1A. RISK FACTORS" vs "Item 1A. Risk Factors" vs "Item 1A: Risk
Factors").

Whitespace handling: every pattern uses ``\\s+`` for inter-token
whitespace so that the parser can match across regular spaces, tabs,
and the &nbsp; (\\u00a0) characters issuers use heavily inside their
heading layouts.

Order matters here: ``parse_filing_sections`` walks patterns in declared
order and uses the *first* match per item_id. Putting the most-specific
patterns first (e.g. "Item 1A. Risk Factors" before "Item 1A.") avoids
spurious early matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class SectionSpec:
    """One entry in a form's section taxonomy.

    Attributes
    ----------
    item_id:
        Short retrieval id ("1A", "7", "II.1A", etc.).
    canonical_name:
        Human-readable section name.
    patterns:
        Anchored regex patterns tried directly against a candidate
        block's normalised text. Match here when the heading text
        survives bs4 extraction cleanly.
    alpha_keys:
        Lowercase alphanumeric-only prefix strings tried against the
        candidate block's alpha-collapsed text. This fallback handles
        SEC iXBRL filings (notably MSFT's) where inline tags split
        words mid-character — bs4's ``get_text(separator=" ")`` then
        produces ``"PR OPERTIES"`` instead of ``"PROPERTIES"``. A
        candidate's alpha-collapsed form ("PR OPERTIES" -> "properties")
        ``startswith`` one of these keys means the heading matches.
        First key in the list is the "expected" canonical form; later
        entries are alternates issuers actually use.
    """

    item_id: str
    canonical_name: str
    patterns: list[Pattern[str]]
    alpha_keys: list[str]


def _ci(*patterns: str) -> list[Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _ak(*keys: str) -> list[str]:
    """Helper: lower-case + strip non-alphanumerics from each key so
    callers can pass a readable string ("item 1a risk factors") and the
    parser still matches against the alpha-collapsed candidate text.
    """
    return [re.sub(r"[^a-z0-9]+", "", k.lower()) for k in keys]


# ---------------------------------------------------------------------------
# 10-K — Annual Report
#
# Item numbering is consistent across issuers because Reg S-K mandates it.
# We list the items most often retrieved against; other items (4 mine
# safety, 6 reserved, 9, 10-15 governance) parse fine but rarely matter
# for analyst questions and are intentionally NOT in this taxonomy.
# Anything a retrieval call doesn't match drops into UNKNOWN.
# ---------------------------------------------------------------------------

SECTION_PATTERNS_10K: list[SectionSpec] = [
    SectionSpec(
        "1", "Business",
        _ci(r"^\s*item\s+1\.?\s+business\s*$"),
        _ak("item 1 business"),
    ),
    SectionSpec(
        "1A", "Risk Factors",
        _ci(r"^\s*item\s+1a\.?\s+risk\s+factors\s*$"),
        _ak("item 1a risk factors"),
    ),
    SectionSpec(
        "1B", "Unresolved Staff Comments",
        _ci(r"^\s*item\s+1b\.?\s+unresolved\s+staff\s+comments\s*$"),
        _ak("item 1b unresolved staff comments"),
    ),
    SectionSpec(
        "1C", "Cybersecurity",
        _ci(r"^\s*item\s+1c\.?\s+cybersecurity\s*$"),
        _ak("item 1c cybersecurity"),
    ),
    SectionSpec(
        "2", "Properties",
        _ci(r"^\s*item\s+2\.?\s+properties\s*$"),
        _ak("item 2 properties"),
    ),
    SectionSpec(
        "3", "Legal Proceedings",
        _ci(r"^\s*item\s+3\.?\s+legal\s+proceedings\s*$"),
        _ak("item 3 legal proceedings"),
    ),
    SectionSpec(
        "4", "Mine Safety Disclosures",
        _ci(r"^\s*item\s+4\.?\s+mine\s+safety\s+disclosures\s*$"),
        _ak("item 4 mine safety disclosures"),
    ),
    SectionSpec(
        "5", "Market for Registrant's Common Equity",
        _ci(r"^\s*item\s+5\.?\s+market\s+for\s+(?:the\s+)?(?:registrant'?s|registrant’s)?\s*common\s+equity"),
        _ak(
            "item 5 market for registrants common equity",
            "item 5 market for the registrants common equity",
        ),
    ),
    SectionSpec(
        "7", "Management's Discussion and Analysis",
        _ci(r"^\s*item\s+7\.?\s+management.{0,4}s?\s+discussion\s+and\s+analysis"),
        _ak(
            "item 7 managements discussion and analysis",
            "item 7 management s discussion and analysis",
        ),
    ),
    SectionSpec(
        "7A", "Quantitative and Qualitative Disclosures About Market Risk",
        _ci(r"^\s*item\s+7a\.?\s+quantitative\s+and\s+qualitative\s+disclosures\s+about\s+market\s+risk\s*$"),
        _ak("item 7a quantitative and qualitative disclosures about market risk"),
    ),
    SectionSpec(
        "8", "Financial Statements and Supplementary Data",
        _ci(r"^\s*item\s+8\.?\s+financial\s+statements\s+and\s+supplementary\s+data\s*$"),
        _ak("item 8 financial statements and supplementary data"),
    ),
    SectionSpec(
        "9", "Changes in and Disagreements With Accountants",
        _ci(r"^\s*item\s+9\.?\s+changes\s+in\s+and\s+disagreements\s+with\s+accountants"),
        _ak("item 9 changes in and disagreements with accountants"),
    ),
    SectionSpec(
        "9A", "Controls and Procedures",
        _ci(r"^\s*item\s+9a\.?\s+controls\s+and\s+procedures\s*$"),
        _ak("item 9a controls and procedures"),
    ),
    SectionSpec(
        "9B", "Other Information",
        _ci(r"^\s*item\s+9b\.?\s+other\s+information\s*$"),
        _ak("item 9b other information"),
    ),
]


# ---------------------------------------------------------------------------
# 10-Q — Quarterly Report
#
# 10-Qs are split into Part I (financial information) and Part II (other
# information). The Item numbering RESETS at Part II, so we encode the
# Part prefix in the item_id ("II.1" etc.) to keep the retrieval key
# unambiguous.
# ---------------------------------------------------------------------------

SECTION_PATTERNS_10Q: list[SectionSpec] = [
    SectionSpec(
        "I.1", "Financial Statements",
        _ci(r"^\s*item\s+1\.?\s+financial\s+statements\s*$"),
        _ak("item 1 financial statements"),
    ),
    SectionSpec(
        "I.2", "Management's Discussion and Analysis",
        _ci(r"^\s*item\s+2\.?\s+management.{0,4}s?\s+discussion\s+and\s+analysis"),
        _ak(
            "item 2 managements discussion and analysis",
            "item 2 management s discussion and analysis",
        ),
    ),
    SectionSpec(
        "I.3", "Quantitative and Qualitative Disclosures About Market Risk",
        _ci(r"^\s*item\s+3\.?\s+quantitative\s+and\s+qualitative\s+disclosures\s+about\s+market\s+risk\s*$"),
        _ak("item 3 quantitative and qualitative disclosures about market risk"),
    ),
    SectionSpec(
        "I.4", "Controls and Procedures",
        _ci(r"^\s*item\s+4\.?\s+controls\s+and\s+procedures\s*$"),
        _ak("item 4 controls and procedures"),
    ),
    SectionSpec(
        "II.1", "Legal Proceedings",
        _ci(r"^\s*item\s+1\.?\s+legal\s+proceedings\s*$"),
        _ak("item 1 legal proceedings"),
    ),
    SectionSpec(
        "II.1A", "Risk Factors",
        _ci(r"^\s*item\s+1a\.?\s+risk\s+factors\s*$"),
        _ak("item 1a risk factors"),
    ),
    SectionSpec(
        "II.2", "Unregistered Sales of Equity Securities",
        _ci(r"^\s*item\s+2\.?\s+unregistered\s+sales\s+of\s+equity\s+securities"),
        _ak("item 2 unregistered sales of equity securities"),
    ),
    SectionSpec(
        "II.5", "Other Information",
        _ci(r"^\s*item\s+5\.?\s+other\s+information\s*$"),
        _ak("item 5 other information"),
    ),
    SectionSpec(
        "II.6", "Exhibits",
        _ci(r"^\s*item\s+6\.?\s+exhibits\s*$"),
        _ak("item 6 exhibits"),
    ),
]


# ---------------------------------------------------------------------------
# 8-K — Current Report
#
# 8-K items follow the four-digit "X.YZ" scheme set out in Form 8-K.
# These are the items most often retrieved against in equity research /
# due-diligence work; the long tail (1.04 mine safety, 4.01 auditor change,
# 6.01 ABS reports, etc.) drops into UNKNOWN and is fine for Phase 1.
# ---------------------------------------------------------------------------

SECTION_PATTERNS_8K: list[SectionSpec] = [
    SectionSpec(
        "1.01", "Entry into a Material Definitive Agreement",
        _ci(r"^\s*item\s+1\.01\.?\s+entry\s+into\s+a\s+material\s+definitive\s+agreement\s*$"),
        _ak("item 1.01 entry into a material definitive agreement"),
    ),
    SectionSpec(
        "1.02", "Termination of a Material Definitive Agreement",
        _ci(r"^\s*item\s+1\.02\.?\s+termination\s+of\s+a\s+material\s+definitive\s+agreement\s*$"),
        _ak("item 1.02 termination of a material definitive agreement"),
    ),
    SectionSpec(
        "2.01", "Completion of Acquisition or Disposition of Assets",
        _ci(r"^\s*item\s+2\.01\.?\s+completion\s+of\s+acquisition\s+or\s+disposition\s+of\s+assets\s*$"),
        _ak("item 2.01 completion of acquisition or disposition of assets"),
    ),
    SectionSpec(
        "2.02", "Results of Operations and Financial Condition",
        _ci(r"^\s*item\s+2\.02\.?\s+results\s+of\s+operations\s+and\s+financial\s+condition\s*$"),
        _ak("item 2.02 results of operations and financial condition"),
    ),
    SectionSpec(
        "2.03", "Creation of a Direct Financial Obligation",
        _ci(r"^\s*item\s+2\.03\.?\s+creation\s+of\s+a\s+direct\s+financial\s+obligation"),
        _ak("item 2.03 creation of a direct financial obligation"),
    ),
    SectionSpec(
        "3.01", "Notice of Delisting or Failure to Satisfy a Listing Rule",
        _ci(r"^\s*item\s+3\.01\.?\s+notice\s+of\s+delisting"),
        _ak("item 3.01 notice of delisting"),
    ),
    SectionSpec(
        "3.02", "Unregistered Sales of Equity Securities",
        _ci(r"^\s*item\s+3\.02\.?\s+unregistered\s+sales\s+of\s+equity\s+securities\s*$"),
        _ak("item 3.02 unregistered sales of equity securities"),
    ),
    SectionSpec(
        "5.02", "Departure of Directors or Certain Officers",
        _ci(r"^\s*item\s+5\.02\.?\s+departure\s+of\s+directors"),
        _ak("item 5.02 departure of directors"),
    ),
    SectionSpec(
        "5.03", "Amendments to Articles of Incorporation or Bylaws",
        _ci(r"^\s*item\s+5\.03\.?\s+amendments\s+to\s+articles"),
        _ak("item 5.03 amendments to articles of incorporation or bylaws"),
    ),
    SectionSpec(
        "5.07", "Submission of Matters to a Vote of Security Holders",
        _ci(r"^\s*item\s+5\.07\.?\s+submission\s+of\s+matters\s+to\s+a\s+vote"),
        _ak("item 5.07 submission of matters to a vote of security holders"),
    ),
    SectionSpec(
        "7.01", "Regulation FD Disclosure",
        _ci(r"^\s*item\s+7\.01\.?\s+regulation\s+fd\s+disclosure\s*$"),
        _ak("item 7.01 regulation fd disclosure"),
    ),
    SectionSpec(
        "8.01", "Other Events",
        _ci(r"^\s*item\s+8\.01\.?\s+other\s+events\s*$"),
        _ak("item 8.01 other events"),
    ),
    SectionSpec(
        "9.01", "Financial Statements and Exhibits",
        _ci(r"^\s*item\s+9\.01\.?\s+financial\s+statements\s+and\s+exhibits\s*$"),
        _ak("item 9.01 financial statements and exhibits"),
    ),
]


# ---------------------------------------------------------------------------
# DEF 14A — Definitive Proxy Statement
#
# DEF 14As don't have item numbers like 10-K / 8-K do. We tag by the
# headings issuers typically use; ``item_id`` is a slug that retrieval
# can reason about without colliding with 10-K item ids.
# ---------------------------------------------------------------------------

SECTION_PATTERNS_DEF14A: list[SectionSpec] = [
    SectionSpec(
        "notice", "Notice of Annual Meeting",
        _ci(r"^\s*notice\s+of\s+(?:annual|special)\s+meeting"),
        _ak("notice of annual meeting", "notice of special meeting"),
    ),
    SectionSpec(
        "proxy_summary", "Proxy Statement Summary",
        _ci(r"^\s*proxy\s+statement\s+summary\s*$"),
        _ak("proxy statement summary"),
    ),
    SectionSpec(
        "election", "Election of Directors",
        _ci(r"^\s*(?:proposal\s+\d+\s*[\.:]?\s*)?election\s+of\s+directors\s*$"),
        _ak("election of directors", "proposal 1 election of directors"),
    ),
    SectionSpec(
        "governance", "Corporate Governance",
        _ci(r"^\s*corporate\s+governance(?:\s+matters)?\s*$"),
        _ak("corporate governance", "corporate governance matters"),
    ),
    SectionSpec(
        "compensation_discussion", "Executive Compensation",
        _ci(
            r"^\s*compensation\s+discussion\s+and\s+analysis\s*$",
            r"^\s*executive\s+compensation\s*$",
        ),
        _ak(
            "compensation discussion and analysis",
            "executive compensation",
        ),
    ),
    SectionSpec(
        "audit_committee", "Audit Committee Report",
        _ci(r"^\s*audit\s+committee\s+report\s*$"),
        _ak("audit committee report"),
    ),
    SectionSpec(
        "auditor_ratification", "Ratification of Auditor",
        _ci(r"^\s*(?:proposal\s+\d+\s*[\.:]?\s*)?ratification\s+of\s+(?:the\s+)?(?:appointment\s+of\s+)?(?:independent\s+)?(?:registered\s+public\s+)?accounting\s+firm"),
        _ak(
            "ratification of independent registered public accounting firm",
            "ratification of appointment of independent registered public accounting firm",
        ),
    ),
    SectionSpec(
        "stockholder_proposals", "Stockholder Proposals",
        _ci(r"^\s*stockholder\s+proposals?\s*$", r"^\s*shareholder\s+proposals?\s*$"),
        _ak("stockholder proposals", "shareholder proposals"),
    ),
    SectionSpec(
        "voting_information", "Voting Information",
        _ci(r"^\s*(?:questions\s+and\s+answers\s+about\s+)?(?:the\s+)?voting(?:\s+information|\s+procedures)?\s*$"),
        _ak("voting information", "questions and answers about voting"),
    ),
]


# ---------------------------------------------------------------------------
# S-1 — Registration Statement (IPO prospectus)
#
# S-1s carry the "Prospectus" structure: summary, risk factors, use of
# proceeds, capitalization, MD&A, business, management, principal
# stockholders, underwriting, financial statements. No item numbers; we
# tag by canonical heading.
# ---------------------------------------------------------------------------

SECTION_PATTERNS_S1: list[SectionSpec] = [
    SectionSpec(
        "summary", "Prospectus Summary",
        _ci(r"^\s*prospectus\s+summary\s*$", r"^\s*summary\s*$"),
        _ak("prospectus summary"),
    ),
    SectionSpec(
        "risk_factors", "Risk Factors",
        _ci(r"^\s*risk\s+factors\s*$"),
        _ak("risk factors"),
    ),
    SectionSpec(
        "use_of_proceeds", "Use of Proceeds",
        _ci(r"^\s*use\s+of\s+proceeds\s*$"),
        _ak("use of proceeds"),
    ),
    SectionSpec(
        "capitalization", "Capitalization",
        _ci(r"^\s*capitalization\s*$"),
        _ak("capitalization"),
    ),
    SectionSpec(
        "dilution", "Dilution",
        _ci(r"^\s*dilution\s*$"),
        _ak("dilution"),
    ),
    SectionSpec(
        "mda", "Management's Discussion and Analysis",
        _ci(r"^\s*management.{0,4}s?\s+discussion\s+and\s+analysis(?:\s+of\s+financial\s+condition)?"),
        _ak(
            "managements discussion and analysis",
            "management s discussion and analysis",
        ),
    ),
    SectionSpec(
        "business", "Business",
        _ci(r"^\s*business\s*$"),
        _ak("business"),
    ),
    SectionSpec(
        "management", "Management",
        _ci(r"^\s*management\s*$"),
        _ak("management"),
    ),
    SectionSpec(
        "executive_compensation", "Executive Compensation",
        _ci(r"^\s*executive\s+compensation\s*$"),
        _ak("executive compensation"),
    ),
    SectionSpec(
        "principal_stockholders", "Principal Stockholders",
        _ci(r"^\s*principal\s+(?:and\s+selling\s+)?stockholders?\s*$"),
        _ak("principal stockholders", "principal and selling stockholders"),
    ),
    SectionSpec(
        "related_party", "Certain Relationships and Related Party Transactions",
        _ci(r"^\s*certain\s+relationships\s+and\s+related\s+party\s+transactions\s*$"),
        _ak("certain relationships and related party transactions"),
    ),
    SectionSpec(
        "underwriting", "Underwriting",
        _ci(r"^\s*underwriting\s*$", r"^\s*plan\s+of\s+distribution\s*$"),
        _ak("underwriting", "plan of distribution"),
    ),
    SectionSpec(
        "financial_statements", "Financial Statements",
        _ci(
            r"^\s*(?:index\s+to\s+)?(?:consolidated\s+)?financial\s+statements\s*$",
        ),
        _ak(
            "financial statements",
            "consolidated financial statements",
            "index to financial statements",
            "index to consolidated financial statements",
        ),
    ),
]


def patterns_for(form: str) -> list[SectionSpec]:
    """Return the section taxonomy for a SEC form.

    Falls back to ``SECTION_PATTERNS_10K`` for any unrecognised form so
    the parser can attempt extraction (anything unmatched ends up in
    UNKNOWN regardless).
    """
    f = (form or "").strip().upper()
    if f == "10-Q":
        return SECTION_PATTERNS_10Q
    if f == "8-K":
        return SECTION_PATTERNS_8K
    if f == "DEF 14A":
        return SECTION_PATTERNS_DEF14A
    if f == "S-1":
        return SECTION_PATTERNS_S1
    return SECTION_PATTERNS_10K


# Item id used for the catch-all bucket — content the parser couldn't
# tag as belonging to a known item. Public so the chunker can filter
# / report on it.
UNKNOWN_ITEM_ID = "UNKNOWN"
UNKNOWN_CANONICAL_NAME = "Unrecognised Section"
