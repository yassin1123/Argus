"""Named-entity extraction for the lexical-overlap signal.

Phase 1 / Week 2 / Day 2. Pulls organisations, geopolitical entities,
products, laws/regulations, and nationalities/religions/political
groups (NORP) from claim and chunk text via spaCy en_core_web_sm.

Why we filter the labels we keep:
- ``CARDINAL``, ``MONEY``, ``PERCENT``, ``DATE``, ``QUANTITY``, ``ORDINAL``
  are all numeric/temporal signals. spaCy's coverage there is unreliable
  (currency variants in particular are hit-and-miss), so the numeric
  normalizer (regex-driven) owns those instead.
- ``ORG / GPE / PRODUCT / LAW / NORP`` are categorical entities the
  numeric path can't see. These are the labels we want to count overlap
  on.
- ``PERSON / FAC / EVENT / WORK_OF_ART / LOC / LANGUAGE`` are skipped
  because they tend to introduce noise on the kinds of consulting text
  Argus produces (model paraphrases people's titles, mentions cities
  that aren't load-bearing for the claim, etc.). We can re-add them
  later if the lexical signal under-fires.

This module imports spaCy at module load (cheap) and lazily loads the
``en_core_web_sm`` model on first call (~50MB; cached in the image so
~1s on cold container start).
"""

from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass
from threading import Lock

import spacy
from spacy.language import Language

logger = logging.getLogger(__name__)

MODEL_NAME = "en_core_web_sm"
KEPT_LABELS: frozenset[str] = frozenset({"ORG", "GPE", "PRODUCT", "LAW", "NORP"})


@dataclass(frozen=True)
class Entity:
    """A canonicalised named entity.

    Attributes
    ----------
    label:
        spaCy entity label (one of ``KEPT_LABELS``).
    canonical:
        Lowercased, punctuation-stripped, whitespace-collapsed text. This
        is what the lexical-overlap scorer compares for equality.
    raw_text:
        The exact substring of the source text spaCy tagged.
    span:
        Half-open (start, end) character offsets in the source text.
    """

    label: str
    canonical: str
    raw_text: str
    span: tuple[int, int] = (0, 0)


# ---------------------------------------------------------------------------
# Lazy model loading (process-level cache, thread-safe)
# ---------------------------------------------------------------------------

_NLP: Language | None = None
_NLP_LOCK = Lock()


def _load_nlp() -> Language:
    global _NLP
    if _NLP is not None:
        return _NLP
    with _NLP_LOCK:
        if _NLP is not None:
            return _NLP
        logger.info("Loading spaCy model: %s", MODEL_NAME)
        # We only need the NER pipeline; disable parser + tagger to halve
        # the memory and load time. The default pipeline is already small,
        # but every saved MB matters when this lives alongside the other
        # main-worker dependencies.
        _NLP = spacy.load(MODEL_NAME, disable=["parser", "lemmatizer"])
        return _NLP


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------

# Strip leading/trailing punctuation but keep internal hyphens / apostrophes
# only when they connect alphanumerics (so "North Rhine-Westphalia" canonicalises
# to "north rhine westphalia", not "northrhinewestphalia").
_PUNCT_TABLE = str.maketrans({c: " " for c in string.punctuation})
_WS_RE = re.compile(r"\s+")


def _canonicalise(text: str) -> str:
    """Lowercase, replace punctuation with whitespace, collapse runs of
    whitespace to one space, strip ends.

    "North Rhine-Westphalia" -> "north rhine westphalia"
    "U.S." -> "u s"
    "  Apple, Inc.  " -> "apple inc"
    """
    if not text:
        return ""
    lowered = text.lower()
    no_punct = lowered.translate(_PUNCT_TABLE)
    return _WS_RE.sub(" ", no_punct).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_entities(text: str) -> list[Entity]:
    """Return every ORG/GPE/PRODUCT/LAW/NORP entity in ``text``, canonicalised.

    Duplicate canonical forms are deduplicated (so the lexical-overlap
    scorer doesn't double-count "Germany" appearing twice in one claim).
    """
    if not text or not text.strip():
        return []
    nlp = _load_nlp()
    doc = nlp(text)
    seen_canonicals: set[tuple[str, str]] = set()
    out: list[Entity] = []
    for ent in doc.ents:
        if ent.label_ not in KEPT_LABELS:
            continue
        canonical = _canonicalise(ent.text)
        if not canonical:
            continue
        key = (ent.label_, canonical)
        if key in seen_canonicals:
            continue
        seen_canonicals.add(key)
        out.append(
            Entity(
                label=ent.label_,
                canonical=canonical,
                raw_text=ent.text,
                span=(ent.start_char, ent.end_char),
            )
        )
    return out


def entities_match(a: Entity, b: Entity) -> bool:
    """True if the two entities should be treated as the same mention.

    Match is on canonical form only; we ignore the spaCy label because
    it occasionally swaps ORG/GPE on country-as-organisation references
    (e.g., "Germany" tagged GPE in one sentence and ORG in another) and
    we don't want that to break overlap. If two strings canonicalise to
    the same thing, they're the same entity for our purposes.
    """
    return bool(a.canonical) and a.canonical == b.canonical
