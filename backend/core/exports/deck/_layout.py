"""Shared layout + styling helpers for deck slides — W11/D1.

Centralises pptx unit math, color parsing, font/size constants, and
the colour-coding rules for recommendation verdicts. Per-mode slides
import from here to stay consistent without re-importing pptx's
verbose unit helpers each time.

Hard constraint per spec: no images embedded today, no external
asset fetching — logo URL is ignored on Day 1, falling back to
firm name as text on the title slide.
"""

from __future__ import annotations

from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# Standard 16:9 slide is 13.333 x 7.5 inches.
SLIDE_WIDTH_IN = 13.333
SLIDE_HEIGHT_IN = 7.5

# Default font stack — Calibri ships with PowerPoint/Office on macOS
# + Windows; LibreOffice falls back gracefully.
DEFAULT_FONT = "Calibri"

# Brand defaults if firms.branding is unset (matches the W10 1-pager
# defaults so HTML + PDF + PPTX visually agree).
DEFAULT_PRIMARY = "#0F6E56"
DEFAULT_SECONDARY = "#1B1F23"
DEFAULT_MUTED = "#5b6470"

# Recommendation verdict colour map. Mirrors W10's classify_recommendation
# rules so the deck's exec-summary panel matches the HTML/PDF 1-pager.
_VERDICT_COLOURS: dict[str, str] = {
    "green": "#0F6E56",
    "amber": "#B8860B",
    "red":   "#B91C1C",
    "neutral": "#1B1F23",
}


def parse_hex(value: Any, default: str = "#1B1F23") -> RGBColor:
    """Parse ``"#RRGGBB"`` (case-insensitive) into a pptx RGBColor.
    Falls back to ``default`` on bad input — never raises, because a
    bad branding row shouldn't crash the deck render."""
    if not isinstance(value, str):
        value = default
    s = value.strip().lstrip("#")
    if len(s) != 6:
        s = default.strip().lstrip("#")
    try:
        return RGBColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        d = default.strip().lstrip("#")
        return RGBColor(int(d[0:2], 16), int(d[2:4], 16), int(d[4:6], 16))


def verdict_colour(klass: str) -> RGBColor:
    """Map ``classify_recommendation`` outputs (green/amber/red/neutral)
    to a pptx RGBColor."""
    return parse_hex(_VERDICT_COLOURS.get(klass, DEFAULT_SECONDARY))


def set_slide_size_16_9(presentation: Any) -> None:
    """Force the presentation to 16:9 regardless of the default
    layout master, so slides render the same shape on PowerPoint,
    Keynote and LibreOffice."""
    presentation.slide_width = Inches(SLIDE_WIDTH_IN)
    presentation.slide_height = Inches(SLIDE_HEIGHT_IN)


def add_blank_slide(presentation: Any) -> Any:
    """Use the blank layout — index 6 by convention in the default
    pptx master. Falls back to the last available layout if a custom
    master has fewer slides."""
    layouts = presentation.slide_layouts
    blank_idx = 6 if len(layouts) > 6 else len(layouts) - 1
    return presentation.slides.add_slide(layouts[blank_idx])


def add_textbox(
    slide: Any,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str = "",
    font_size: int = 14,
    bold: bool = False,
    color: RGBColor | None = None,
    align: int = PP_ALIGN.LEFT,
    anchor: int = MSO_ANCHOR.TOP,
    font_name: str = DEFAULT_FONT,
    word_wrap: bool = True,
) -> Any:
    """Wrap pptx's verbose ``add_textbox`` + paragraph setup. Accepts
    inches as floats, returns the shape so the caller can mutate the
    text further (e.g. add multiple paragraphs)."""
    shape = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = shape.text_frame
    tf.word_wrap = word_wrap
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    if text:
        run = p.add_run()
        run.text = text
        run.font.name = font_name
        run.font.size = Pt(font_size)
        run.font.bold = bold
        if color is not None:
            run.font.color.rgb = color
    return shape


def add_paragraph(
    text_frame: Any,
    text: str,
    *,
    font_size: int = 12,
    bold: bool = False,
    color: RGBColor | None = None,
    bullet: bool = False,
    align: int = PP_ALIGN.LEFT,
    font_name: str = DEFAULT_FONT,
) -> Any:
    """Append a paragraph to an existing text frame. ``bullet`` is a
    textual indicator only (we prefix ``"• "``) — pptx's native
    bullet formatting is layout-master-dependent and inconsistent
    across renderers; a literal bullet character is portable."""
    p = text_frame.add_paragraph()
    p.alignment = align
    run = p.add_run()
    run.text = ("• " + text) if bullet else text
    run.font.name = font_name
    run.font.size = Pt(font_size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    return p


def add_horizontal_band(
    slide: Any,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    color_hex: str,
) -> Any:
    """Solid coloured rectangle, used for header bands + the
    recommendation verdict band on the exec-summary slide.

    We use a textbox with a solid fill rather than ``add_shape`` so
    we keep the same kind-of-element across slides (simplifies tests
    that inspect ``slide.shapes``)."""
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left), Inches(top), Inches(width), Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = parse_hex(color_hex)
    shape.line.fill.background()
    return shape
