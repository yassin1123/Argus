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
# Day 1 base trio:
from . import exec_summary  # noqa: F401,E402
from . import recommendation  # noqa: F401,E402
from . import title_slide  # noqa: F401,E402

# Day 2 mode-agnostic content slides:
from . import context  # noqa: F401,E402
from . import next_steps  # noqa: F401,E402
from . import risks_matrix  # noqa: F401,E402
from . import sources  # noqa: F401,E402

# Day 2 M&A-specific:
from . import financial_profile  # noqa: F401,E402
from . import integration_plan  # noqa: F401,E402
from . import target_overview  # noqa: F401,E402
from . import valuation_range  # noqa: F401,E402

# Day 2 growth-specific:
from . import market_landscape  # noqa: F401,E402
from . import options_matrix  # noqa: F401,E402

# Day 3 framework visuals (replace text stubs):
from . import porters_visual  # noqa: F401,E402
from . import two_by_two_visual  # noqa: F401,E402

__all__ = [
    "SlideBuilderBase",
    "SlideResult",
    "get_slide_builder",
    "list_registered_slides",
    "register_slide",
]
