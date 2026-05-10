"""GeneralReportPayload — the default writer schema.

Every existing built-in mode (``general``, ``market_entry``,
``due_diligence``, ``growth_strategy``) routes through this class via
the registry until they get their own bespoke schema. Field set is
identical to ``WriterReportBase`` — no extras — so this is the safe
fallback for unknown modes (including firm-defined modes that don't
declare a custom schema).

``mode`` is intentionally a free string here (not a ``Literal``):
multiple consulting modes share this concrete class via the registry,
each writing its own slug into the field for self-description. Mode-
specific schemas (e.g. ``MAndADiligenceReportPayload``) lock the
field to their slug so a stray mode tag can't slip past the validator.
"""

from __future__ import annotations

from ._base import WriterReportBase


class GeneralReportPayload(WriterReportBase):
    """The pre-W7 ``WriterReportPayload``, unchanged in field shape.

    Subclasses don't override anything; they inherit every validator
    and the ``consulting_payload_dict`` serialiser.
    """
