"""Materialize a memo artifact from a StructuredAnswer.

Output is ProseMirror JSON (TipTap-compatible). Each citation is a custom
inline mark `citation` carrying the chunk_ids referenced.

Schema (informal):
    {
      type: "doc",
      content: [
        {type: "heading", attrs: {level: 1}, content: [{type: "text", text: "..."}]},
        {type: "paragraph", content: [
          {type: "text", text: "Some claim "},
          {type: "text", marks: [{type: "citation", attrs: {chunk_ids: [...], n: 1}}], text: "[1]"},
          {type: "text", text: "."}
        ]},
        ...
      ]
    }
"""

from __future__ import annotations

from typing import Any

from models.structured_answer import GroundedClaim, StructuredAnswer


def _text(s: str) -> dict[str, Any]:
    return {"type": "text", "text": s}


def _heading(level: int, text: str) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [_text(text)] if text else [],
    }


def _paragraph(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


def _bullet_list(items: list[str]) -> dict[str, Any]:
    return {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [_paragraph(_text(item))],
            }
            for item in items
        ],
    }


def _citation_mark(chunk_ids: list[str], n: int) -> dict[str, Any]:
    return {"type": "citation", "attrs": {"chunk_ids": chunk_ids, "n": n}}


def _citation_node(chunk_ids: list[str], n: int) -> dict[str, Any]:
    """Inline `[N]` text node carrying citation marks."""
    return {
        "type": "text",
        "text": f"[{n}]",
        "marks": [_citation_mark(chunk_ids, n)],
    }


def build_memo_document(answer: StructuredAnswer, *, source_titles_by_chunk: dict[str, str] | None = None) -> dict[str, Any]:
    """Convert a StructuredAnswer into a TipTap memo document.

    `source_titles_by_chunk` (chunk_id → "Source title — p.N") is optional and
    used only when rendering the appendix.
    """
    nodes: list[dict[str, Any]] = []

    # Title + TLDR
    nodes.append(_heading(1, "Memo"))
    if answer.tldr:
        nodes.append(_paragraph(_text(answer.tldr)))

    # Number citations as we encounter them so the same chunk gets the same [N].
    chunk_to_n: dict[str, int] = {}

    def cite_for(claim: GroundedClaim) -> int | None:
        if not claim.chunk_ids:
            return None
        # Use the first chunk_id as the canonical one for the [N] marker —
        # but the mark stores ALL chunk_ids so the popover can show all.
        primary = claim.chunk_ids[0]
        if primary not in chunk_to_n:
            chunk_to_n[primary] = len(chunk_to_n) + 1
        return chunk_to_n[primary]

    # Sections
    for section in answer.sections:
        if section.heading:
            nodes.append(_heading(2, section.heading))
        # The section's narrative text becomes a paragraph; each claim's
        # text within it gets a citation marker appended.
        if section.text:
            nodes.append(_paragraph(_text(section.text)))
        # Claims as bullets — each with an inline citation marker.
        if section.claims:
            bullet_items: list[dict[str, Any]] = []
            for claim in section.claims:
                n = cite_for(claim)
                content: list[dict[str, Any]] = [_text(claim.text + " ")]
                if n is not None:
                    content.append(_citation_node(claim.chunk_ids, n))
                # If NLI flagged the claim contested, append a small marker.
                if claim.confidence == "contested":
                    content.append(_text(" "))
                    content.append(
                        {
                            "type": "text",
                            "text": "⚠ unverified",
                            "marks": [{"type": "italic"}],
                        }
                    )
                bullet_items.append(
                    {"type": "listItem", "content": [_paragraph(*content)]}
                )
            nodes.append({"type": "bulletList", "content": bullet_items})

    # Caveats
    if answer.caveats:
        nodes.append(_heading(2, "Caveats"))
        nodes.append(_paragraph(_text(answer.caveats)))

    # Validation notes (verifier output)
    if answer.validation_notes:
        nodes.append(_heading(3, "Verification notes"))
        nodes.append(_bullet_list(answer.validation_notes))

    # Sources appendix
    if chunk_to_n:
        nodes.append(_heading(2, "Sources"))
        ordered = sorted(chunk_to_n.items(), key=lambda x: x[1])
        items: list[str] = []
        for cid, n in ordered:
            label = (source_titles_by_chunk or {}).get(cid, "Source")
            items.append(f"[{n}] {label}")
        nodes.append(_bullet_list(items))

    return {"type": "doc", "content": nodes}


def collect_chunk_ids(answer: StructuredAnswer) -> list[str]:
    seen: dict[str, None] = {}
    for s in answer.sections:
        for c in s.claims:
            for cid in c.chunk_ids:
                if cid not in seen:
                    seen[cid] = None
    return list(seen.keys())
