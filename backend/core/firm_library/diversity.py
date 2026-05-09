"""Source-diversity breakdown helper (Phase 2 / Week 5 / Day 4 ).

Adds firm_library as its own line in engagement summaries:

  Sources cited:
    SEC filings:           N distinct accessions, M chunks
    Earnings transcripts:  N quarter-tuples,      M chunks
    Firm library:          N documents,           M chunks   ← Day 4
    News:                  N domains,             M chunks

Returns plain dicts so the runner / API surface can shape the wire
format. The important contract is that firm_library is its own bucket,
not folded under "uploaded" — design partners look at this number and
need to see how often firm-curated content showed up in citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Mirror the regex used by run_phase1_exit_demo.py — kept in this module
# for reuse without importing the runner script.
_ACCESSION_RE = re.compile(r"/Archives/edgar/data/\d+/(\d{18})/")


def _accession_from_url(url: str) -> str | None:
    if not url:
        return None
    m = _ACCESSION_RE.search(url)
    if not m:
        return None
    nd = m.group(1)
    return f"{nd[:10]}-{nd[10:12]}-{nd[12:]}"


@dataclass
class SourceDiversity:
    """Per-source-type breakdown of a single engagement's citations."""

    sec_filings: dict[str, Any] = field(
        default_factory=lambda: {"distinct_accessions": [], "chunk_citations": 0},
    )
    transcripts: dict[str, Any] = field(
        default_factory=lambda: {"distinct_quarters": [], "chunk_citations": 0},
    )
    firm_library: dict[str, Any] = field(
        default_factory=lambda: {"distinct_documents": [], "chunk_citations": 0},
    )
    news: dict[str, Any] = field(
        default_factory=lambda: {"distinct_domains": [], "chunk_citations": 0},
    )
    ch_filings: dict[str, Any] = field(
        default_factory=lambda: {"distinct_transactions": [], "chunk_citations": 0},
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sec_filings": self.sec_filings,
            "transcripts": self.transcripts,
            "firm_library": self.firm_library,
            "news": self.news,
            "ch_filings": self.ch_filings,
        }

    def to_lines(self) -> list[str]:
        """Render as a list of human-readable summary lines."""
        out: list[str] = []
        if self.sec_filings["chunk_citations"]:
            n = len(self.sec_filings["distinct_accessions"])
            out.append(
                f"  SEC filings:           {n} distinct accessions, "
                f"{self.sec_filings['chunk_citations']} chunks"
            )
        if self.transcripts["chunk_citations"]:
            n = len(self.transcripts["distinct_quarters"])
            out.append(
                f"  Earnings transcripts:  {n} quarter-tuples,      "
                f"{self.transcripts['chunk_citations']} chunks"
            )
        if self.firm_library["chunk_citations"]:
            n = len(self.firm_library["distinct_documents"])
            out.append(
                f"  Firm library:          {n} documents,           "
                f"{self.firm_library['chunk_citations']} chunks"
            )
        if self.news["chunk_citations"]:
            n = len(self.news["distinct_domains"])
            out.append(
                f"  News:                  {n} domains,             "
                f"{self.news['chunk_citations']} chunks"
            )
        if self.ch_filings["chunk_citations"]:
            n = len(self.ch_filings["distinct_transactions"])
            out.append(
                f"  CH filings:            {n} transactions,        "
                f"{self.ch_filings['chunk_citations']} chunks"
            )
        return out


def compute_source_diversity(
    *,
    chunks_by_url_or_filename: dict[str, dict[str, Any]],
    cited_evidence: list[dict[str, Any]],
) -> SourceDiversity:
    """Aggregate per-source-type citation counts.

    Parameters
    ----------
    chunks_by_url_or_filename:
        A lookup keyed first by ``source_url`` (preferred) and as a
        fallback by ``source_filename``. Each value is a chunks-table
        row dict with at least ``source_type`` plus the bucket-specific
        identifier (accession_number / transaction_id / source_domain /
        firm_content_id / metadata.title / quarter / year / ticker).
    cited_evidence:
        Evidence-object dicts that one or more claims actually cited.
        Each must carry ``source_url`` and ``source_title`` so the
        helper can dereference back to the chunk row.
    """
    out = SourceDiversity()
    sec_seen: set[str] = set()
    transcript_seen: set[str] = set()
    firm_doc_seen: set[str] = set()
    news_seen: set[str] = set()
    ch_seen: set[str] = set()

    for ev in cited_evidence:
        url = (ev.get("source_url") or "").strip()
        title = (ev.get("source_title") or "").strip()
        ch = chunks_by_url_or_filename.get(url) if url else None
        if ch is None and title:
            ch = chunks_by_url_or_filename.get(title)
        if not ch:
            continue
        st = (ch.get("source_type") or "").lower()
        if st == "sec_filing":
            acc = ch.get("accession_number") or _accession_from_url(url)
            if acc:
                sec_seen.add(acc)
            out.sec_filings["chunk_citations"] += 1
        elif st == "transcript":
            t = ch.get("ticker")
            q = ch.get("quarter")
            y = ch.get("year")
            if t and q and y:
                transcript_seen.add(f"{t} {q} FY{y}")
            out.transcripts["chunk_citations"] += 1
        elif st == "firm_library":
            fcid = ch.get("firm_content_id") or ch.get("source_filename")
            if fcid:
                firm_doc_seen.add(str(fcid))
            out.firm_library["chunk_citations"] += 1
        elif st == "news":
            d = ch.get("source_domain")
            if d:
                news_seen.add(d)
            out.news["chunk_citations"] += 1
        elif st == "ch_filing":
            tx = ch.get("transaction_id")
            if tx:
                ch_seen.add(tx)
            out.ch_filings["chunk_citations"] += 1

    out.sec_filings["distinct_accessions"] = sorted(sec_seen)
    out.transcripts["distinct_quarters"] = sorted(transcript_seen)
    out.firm_library["distinct_documents"] = sorted(firm_doc_seen)
    out.news["distinct_domains"] = sorted(news_seen)
    out.ch_filings["distinct_transactions"] = sorted(ch_seen)
    return out
