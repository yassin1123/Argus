"""Speaker-turn-aware transcript chunker.

Two output modes:

  - **speaker_turn** (preferred when the input has speaker labels) — emits
    one chunk per speaker turn. For Q&A turns, prepends a context window
    of up to 2 prior turns so an analyst's question chunk includes the
    operator's intro / earlier exchange.
  - **paragraph** (fallback when the parser can't find speaker labels) —
    paragraph-aware chunking, similar to the EDGAR chunker. Used for
    AI-generated transcripts and articles that summarise a call without
    preserving turns.

The detection regex is liberal: it matches "Tim Cook:" / "Tim Cook -
CEO:" / "Tim Cook - Apple, CEO:" / "[CEO Tim Cook]:" / "Operator:" /
"Wamsi Mohan, Bank of America - Analyst:" — the formats that turn up
across Apple / Microsoft / Tesla / smaller-filer transcripts. The
``Q&A`` boundary is sniffed off any of:
  - a header line containing "Question-and-Answer" / "Q&A" / "Q & A";
  - the operator opening Q&A: "...we'll now begin the question-and-answer
    portion of the call..." / "Operator: Thank you. ... We'll begin the
    Q&A...";
  - the first analyst-from-firm speaker label after at least one
    company-officer turn.

The chunker emits TranscriptChunk objects which the ingestion path
converts to ``chunks`` rows with ``source_type='transcript'`` and the
metadata dict the rest of the pipeline expects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

# Detect a speaker label line. A speaker label is a line that:
#   - starts with a name (one or more capitalised tokens, possibly with
#     periods/hyphens for "C. Cook" or "JP-Morgan" style),
#   - optionally followed by " - Role" or ", Firm" (or both),
#   - ends in a colon.
# We keep the regex anchored to start-of-line and allow up to 80 chars
# before the colon to avoid catching mid-sentence colons (e.g.
# "Revenue: $94B" would NOT match because "Revenue" is a single token
# without role/firm shape).
_SPEAKER_LABEL_RE = re.compile(
    r"""
    ^                                                # line start
    (?P<label>
      (?:Operator|Moderator|Analyst|CEO|CFO|COO)     # role-only labels
      |
      (?:                                            # named-speaker labels
        \[?                                          # optional bracket
        (?P<name>[A-Z][\w'.\-]+(?:\s+[A-Z][\w'.\-]+){0,4})
        \]?
        (?:                                          # optional " - Role"
          \s*[-–—]\s*
          (?P<role>[A-Z][\w &/]{1,40}?)
        )?
        (?:                                          # optional ", Firm"
          \s*,\s*
          (?P<firm>[A-Z][\w &./'\-]{1,60}?)
          (?:                                        # optional " - Role" after firm
            \s*[-–—]\s*
            (?P<role2>[A-Z][\w &/]{1,40}?)
          )?
        )?
      )
    )
    \s*:[ \t]*                                       # the colon, eating only same-line whitespace
    """,
    re.VERBOSE | re.MULTILINE,
)

# Q&A boundary tells, ranked by signal strength.
_QA_BOUNDARY_RES = (
    re.compile(r"\b(?:question[-\s]and[-\s]answer|q\s*&\s*a|q\s*and\s*a)\b", re.IGNORECASE),
    re.compile(r"\bbegin\s+the\s+(?:question[-\s]and[-\s]answer|q\s*&\s*a)", re.IGNORECASE),
    re.compile(r"\bnow\s+open\s+the\s+(?:line|call|floor)\s+(?:up\s+)?(?:for|to)\s+questions", re.IGNORECASE),
)

# The minimum body length we'll emit as a standalone chunk. Shorter
# turns ("Operator: thank you, next question.") get folded into the
# context window of the next substantive turn rather than living as
# their own row.
_MIN_TURN_BODY_CHARS: int = 80

# Paragraph-fallback chunk-size targets — match the EDGAR chunker's defaults.
_DEFAULT_TARGET_CHUNK_CHARS: int = 2000
_DEFAULT_OVERLAP_CHARS: int = 200

# Q&A context window: how many prior turns to prepend to each Q&A turn's
# content so the analyst's question reads with its setup.
_QA_CONTEXT_TURNS: int = 2

# Role inference table for plain "Tim Cook:" labels — keeps metadata
# useful when the speaker doesn't include their role in the label.
# Extend per-company over time; staying small for Phase 1.
_ROLE_INFERENCE: dict[str, str] = {
    # Apple
    "tim cook": "CEO",
    "luca maestri": "CFO",
    "kevan parekh": "CFO",
    "saori casey": "VP, Finance",
    # Microsoft
    "satya nadella": "CEO",
    "amy hood": "CFO",
    "brett iversen": "VP, Investor Relations",
    # Tesla
    "elon musk": "CEO",
    "vaibhav taneja": "CFO",
    "travis axelrod": "Head of IR",
    # Generic
    "operator": "Operator",
    "moderator": "Moderator",
}


@dataclass(frozen=True)
class TranscriptChunk:
    """One chunk emitted by :func:`chunk_transcript`.

    Attributes
    ----------
    content:
        The text body that will be embedded + indexed.
    speaker:
        Best-effort speaker name. Empty string when paragraph-fallback fires.
    role:
        Best-effort role (CEO / CFO / Operator / Analyst). May be empty.
    firm:
        Affiliated firm if the speaker is an external analyst. Empty for
        company officers and operators.
    segment:
        ``'prepared_remarks'`` or ``'qa'``. ``'unknown'`` only when the
        paragraph-fallback fires AND we can't sniff a Q&A boundary
        anywhere in the document.
    turn_index:
        Zero-based index of this turn in the full transcript. Stable
        across re-runs.
    char_offset_in_transcript:
        Character offset of this turn's first byte in the original
        transcript text, useful for downstream highlighting.
    context_prefix:
        When non-empty, the prior-turn context that was prepended to
        ``content`` (Q&A turns only). Empty for prepared_remarks turns
        and paragraph-fallback chunks.
    """

    content: str
    speaker: str
    role: str
    firm: str
    segment: str  # "prepared_remarks" | "qa" | "unknown"
    turn_index: int
    char_offset_in_transcript: int
    context_prefix: str = ""


# ---------------------------------------------------------------------------
# Public detection
# ---------------------------------------------------------------------------


def detect_speaker_turn_format(text: str) -> bool:
    """Return True when the document looks like a speaker-turn transcript.

    Heuristic: at least 3 distinct speaker-label lines AND at least one
    of them is a non-Operator label (so a press release with a single
    "Operator:" header doesn't trip the detector).
    """
    if not text:
        return False
    seen: set[str] = set()
    for m in _SPEAKER_LABEL_RE.finditer(text):
        label = (m.group("label") or "").strip()
        if not label:
            continue
        seen.add(label.lower())
        if len(seen) >= 3:
            break
    if len(seen) < 3:
        return False
    return any(s != "operator" for s in seen)


# ---------------------------------------------------------------------------
# Speaker-turn parser
# ---------------------------------------------------------------------------


def _qa_anchor_offset(text: str, *, after_offset: int = 0) -> int | None:
    """Return the char offset of the earliest Q&A-boundary marker, or None.

    Only considers matches at or after ``after_offset``. Callers pass the
    offset of the first speaker label so a Q&A mention inside a pre-call
    blurb (e.g. an introductory note that lists "Q&A" as a section
    expected later) doesn't false-positive as the boundary.
    """
    best: int | None = None
    for pat in _QA_BOUNDARY_RES:
        for m in pat.finditer(text):
            if m.start() < after_offset:
                continue
            if best is None or m.start() < best:
                best = m.start()
            break  # next pattern; finditer is already sorted
    return best


def _normalise_role(label: str, role: str | None, role2: str | None) -> str:
    role_text = (role or role2 or "").strip()
    if role_text:
        return role_text
    inferred = _ROLE_INFERENCE.get(label.strip().lower())
    return inferred or ""


def _normalise_speaker(label: str, name: str | None) -> str:
    if name and name.strip():
        return name.strip()
    return label.strip()


def _split_into_turns(text: str) -> list[dict[str, Any]]:
    """Walk the document and return one record per speaker turn.

    Each record: {speaker, role, firm, body, char_offset}.
    """
    turns: list[dict[str, Any]] = []
    matches = list(_SPEAKER_LABEL_RE.finditer(text))
    if not matches:
        return turns
    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        label = (m.group("label") or "").strip()
        name = m.group("name")
        firm = (m.group("firm") or "").strip()
        role = _normalise_role(label, m.group("role"), m.group("role2"))
        speaker = _normalise_speaker(label, name)
        turns.append(
            {
                "speaker": speaker,
                "role": role,
                "firm": firm,
                "body": body,
                "char_offset": m.start(),
            }
        )
    return turns


def _classify_segments(
    turns: list[dict[str, Any]],
    qa_anchor: int | None,
) -> None:
    """Mutate each turn dict to add a ``segment`` field.

    Rule of thumb: prepared remarks come BEFORE the Q&A anchor. Once we
    cross the anchor, every subsequent turn is in the Q&A segment. If
    we have no anchor but turns include external-firm speakers, the
    first such turn marks the boundary as a fallback.
    """
    if qa_anchor is None:
        # Fallback: first speaker with a non-empty firm (i.e. external
        # analyst) marks the Q&A boundary.
        first_firm_idx: int | None = None
        for i, t in enumerate(turns):
            if t["firm"]:
                first_firm_idx = i
                break
        if first_firm_idx is None:
            for t in turns:
                t["segment"] = "prepared_remarks"
            return
        for i, t in enumerate(turns):
            t["segment"] = "qa" if i >= first_firm_idx else "prepared_remarks"
        return
    for t in turns:
        t["segment"] = "qa" if t["char_offset"] >= qa_anchor else "prepared_remarks"


def _build_speaker_turn_chunks(text: str) -> list[TranscriptChunk]:
    turns = _split_into_turns(text)
    if not turns:
        return []
    # Q&A boundary must come at or after the first speaker turn — a
    # "Q&A" mention in a pre-call blurb (e.g. a synthetic-fixture NOTE)
    # is not the actual boundary.
    first_turn_offset = turns[0]["char_offset"]
    _classify_segments(turns, _qa_anchor_offset(text, after_offset=first_turn_offset))

    out: list[TranscriptChunk] = []
    emitted_idx = 0
    for i, t in enumerate(turns):
        body = t["body"]
        if len(body) < _MIN_TURN_BODY_CHARS:
            # Skip standalone short turns — they'll appear in the
            # context_prefix of the next Q&A turn.
            continue
        # Operator/Moderator turns are never claim-worthy on their own
        # (they introduce the next question or close the call). They're
        # still useful as context for the speaker that follows, which
        # the context_prefix logic captures. Skip emitting them as
        # standalone chunks so retrieval doesn't surface "Our next
        # question is from..." as a stand-alone hit.
        if t["speaker"].strip().lower() in ("operator", "moderator"):
            continue

        context_prefix = ""
        if t["segment"] == "qa" and _QA_CONTEXT_TURNS > 0:
            ctx_pieces: list[str] = []
            for j in range(max(0, i - _QA_CONTEXT_TURNS), i):
                ctx = turns[j]
                ctx_body = ctx["body"]
                # Truncate any single context turn so the prefix doesn't
                # dominate the embedding window — 400 chars is the
                # operator's "next question" or the analyst's preamble.
                if len(ctx_body) > 400:
                    ctx_body = ctx_body[:400].rstrip() + " …"
                speaker_line = ctx["speaker"]
                if ctx["role"]:
                    speaker_line += f" - {ctx['role']}"
                ctx_pieces.append(f"[CONTEXT — {speaker_line}] {ctx_body}")
            context_prefix = "\n".join(ctx_pieces)

        content = (
            f"{context_prefix}\n\n{t['speaker']}: {body}".strip()
            if context_prefix
            else f"{t['speaker']}: {body}"
        )

        out.append(
            TranscriptChunk(
                content=content,
                speaker=t["speaker"],
                role=t["role"],
                firm=t["firm"],
                segment=t["segment"],
                turn_index=emitted_idx,
                char_offset_in_transcript=t["char_offset"],
                context_prefix=context_prefix,
            )
        )
        emitted_idx += 1
    return out


# ---------------------------------------------------------------------------
# Paragraph fallback (when no speaker labels found)
# ---------------------------------------------------------------------------


def _split_paragraphs(text: str) -> list[tuple[int, str]]:
    """Yield (offset, paragraph) pairs. Paragraphs are blank-line-delimited."""
    out: list[tuple[int, str]] = []
    cur: list[str] = []
    cur_start = 0
    pos = 0
    for line in text.splitlines(keepends=True):
        if not cur:
            cur_start = pos
        if line.strip():
            cur.append(line)
        else:
            joined = "".join(cur).strip()
            if joined:
                out.append((cur_start, joined))
            cur = []
        pos += len(line)
    joined = "".join(cur).strip()
    if joined:
        out.append((cur_start, joined))
    return out


def _build_paragraph_chunks(
    text: str,
    *,
    target_chunk_chars: int,
    overlap_chars: int,
) -> list[TranscriptChunk]:
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    qa_anchor = _qa_anchor_offset(text)
    chunks: list[TranscriptChunk] = []
    buf: list[str] = []
    buf_offset = paragraphs[0][0]
    buf_len = 0
    turn_idx = 0

    def _flush(start_offset: int, body_text: str) -> None:
        nonlocal turn_idx
        body_text = body_text.strip()
        if not body_text:
            return
        segment = "unknown"
        if qa_anchor is not None:
            segment = "qa" if start_offset >= qa_anchor else "prepared_remarks"
        chunks.append(
            TranscriptChunk(
                content=body_text,
                speaker="",
                role="",
                firm="",
                segment=segment,
                turn_index=turn_idx,
                char_offset_in_transcript=start_offset,
                context_prefix="",
            )
        )
        turn_idx += 1

    for offset, para in paragraphs:
        if not buf:
            buf_offset = offset
        if buf_len + len(para) + 2 > target_chunk_chars and buf:
            body = "\n\n".join(buf)
            _flush(buf_offset, body)
            # Carry an overlap window from the tail of the flushed chunk.
            tail = body[-overlap_chars:] if overlap_chars > 0 else ""
            buf = [tail, para] if tail else [para]
            buf_offset = offset - len(tail) if tail else offset
            buf_len = sum(len(p) + 2 for p in buf)
        else:
            buf.append(para)
            buf_len += len(para) + 2
    if buf:
        _flush(buf_offset, "\n\n".join(buf))
    return chunks


# ---------------------------------------------------------------------------
# Public chunker
# ---------------------------------------------------------------------------


def chunk_transcript(
    text: str,
    *,
    target_chunk_chars: int = _DEFAULT_TARGET_CHUNK_CHARS,
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
) -> list[TranscriptChunk]:
    """Chunk ``text`` into TranscriptChunk records.

    Picks speaker-turn mode when the document has at least 3 distinct
    speaker labels (one of them non-Operator), else paragraph fallback.
    """
    text = (text or "").strip()
    if not text:
        return []
    if detect_speaker_turn_format(text):
        return _build_speaker_turn_chunks(text)
    return _build_paragraph_chunks(
        text,
        target_chunk_chars=target_chunk_chars,
        overlap_chars=overlap_chars,
    )
