"""Slide builders — W11.

Importing this package triggers registration of every concrete slide
builder via the ``@register_slide`` decorator. Day 1 ships title,
exec_summary, recommendation. Days 2-3 will add target_overview,
synergy, valuation, integration, porters, options_matrix,
critic_findings, sources.
"""

from __future__ import annotations

from ._base import SlideBuilderBase, SlideResult  # noqa: F401
from ._registry import (  # noqa: F401
    get_slide_builder,
    list_registered_slides,
    register_slide,
)

# Importing the concrete modules registers them.
from . import exec_summary  # noqa: F401,E402
from . import recommendation  # noqa: F401,E402
from . import title_slide  # noqa: F401,E402

__all__ = [
    "SlideBuilderBase",
    "SlideResult",
    "get_slide_builder",
    "list_registered_slides",
    "register_slide",
]
