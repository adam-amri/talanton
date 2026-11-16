"""Formatting of the workbook, following the conventions of financial models.

Text colour:
    blue   -> hard-coded figure (published data or assumption)
    black  -> formula
    green  -> link to another sheet
Pale fill -> assumption to edit.

The colours come from a theme. Pick one with `theme = "midnight"` in the
[settings] of the config, and override any colour in a [theme] table.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SIZE = 10
BLACK, WHITE = "000000", "FFFFFF"

FMT_M = '#,##0.0;(#,##0.0);"-"'              # millions, one decimal
FMT_PCT = '0.0%;(0.0%);"-"'
FMT_PCT2 = "0.00%"
FMT_X = '0.0"x";(0.0"x");"-"'
FMT_X2 = '0.00"x"'
FMT_PRICE = '#,##0.00;(#,##0.00);"-"'
FMT_DATE = "yyyy-mm-dd"
FMT_NB = "0.00"
FMT_NB3 = "0.000"
FMT_INT = "0"


@dataclass(frozen=True)
class Theme:
    font: str = "Arial"
    ink: str = "1F2A44"              # titles and section bands
    accent: str = "2E75B6"           # chart bars and valuation tabs
    input: str = "0000FF"            # hard-coded figures
    link: str = "008000"             # links to other sheets
    note: str = "595959"
    assumption_fill: str = "FFF9D6"
    header_fill: str = "F2F2F2"
    rule: str = "A6A6A6"
    tab_assumptions: str = "E0A800"
    tab_data: str = "7F7F7F"
    tab_checks: str = "C00000"


THEMES = {
    "classic": Theme(),
    "midnight": Theme(font="Calibri", ink="0F172A", accent="0EA5E9", assumption_fill="E0F2FE",
                      header_fill="F1F5F9", tab_assumptions="0EA5E9", tab_data="64748B"),
    "forest": Theme(font="Calibri", ink="14532D", accent="15803D", assumption_fill="ECFCCB",
                    header_fill="F0FDF4", tab_assumptions="CA8A04", tab_data="6B7280"),
    "slate": Theme(font="Arial", ink="334155", accent="7C3AED", assumption_fill="EDE9FE",
                   header_fill="F8FAFC", tab_assumptions="7C3AED", tab_data="94A3B8"),
}

_theme = THEMES["classic"]


def make_theme(name: str = "classic", overrides: dict[str, str] | None = None) -> Theme:
    if name not in THEMES:
        raise ValueError(f"Unknown theme {name!r}. Available: {', '.join(THEMES)}.")
    overrides = dict(overrides or {})
    known = {f.name for f in fields(Theme)}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"Unknown theme colour(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(known))}.")
    for key, value in overrides.items():
        if key != "font":
            value = str(value).lstrip("#").upper()
            if len(value) != 6 or any(c not in "0123456789ABCDEF" for c in value):
                raise ValueError(f"Theme colour {key}: expected a six-digit hex colour such as \"1F2A44\".")
            overrides[key] = value
    return replace(THEMES[name], **overrides)


def use(theme: Theme) -> None:
    """Sets the theme used by every helper below."""
    global _theme
    _theme = theme


def theme() -> Theme:
    return _theme


def font(color: str = BLACK, bold: bool = False, italic: bool = False, size: int = SIZE) -> Font:
    return Font(name=_theme.font, size=size, color=color, bold=bold, italic=italic)


def _color(style: str) -> str:
    return {"input": _theme.input, "assumption": _theme.input, "link": _theme.link,
            "note": _theme.note}.get(style, BLACK)


def apply(cell, style: str = "calc", fmt: str | None = None, bold: bool = False,
          total: bool = False, center: bool = False) -> None:
    cell.font = font(_color(style), bold=bold or total, italic=(style == "note"))
    if style == "assumption":
        cell.fill = PatternFill("solid", start_color=_theme.assumption_fill)
    if fmt:
        cell.number_format = fmt
    if total:
        cell.border = Border(top=Side(style="thin", color=_theme.rule))
    if center:
        cell.alignment = Alignment(horizontal="center")
    elif style == "note":
        cell.alignment = Alignment(horizontal="left", indent=1)


def band(ws, row: int, text: str, last_column: int) -> None:
    """Section title: dark band across the whole width of the table."""
    for c in range(1, last_column + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = PatternFill("solid", start_color=_theme.ink)
        cell.font = font(WHITE, bold=True)
    ws.cell(row=row, column=1, value=text)


def header(ws, row: int, texts: dict[str, str], left: tuple[str, ...] = ()) -> None:
    """Column headers: bold, grey fill, right-aligned (left-aligned for text)."""
    for col, text in texts.items():
        cell = ws[f"{col}{row}"]
        cell.value = text
        cell.font = font(bold=True)
        cell.fill = PatternFill("solid", start_color=_theme.header_fill)
        is_left = col == "A" or col in left
        cell.alignment = Alignment(horizontal="left" if is_left else "right", indent=1 if col in left else 0)
        cell.border = Border(bottom=Side(style="thin", color=_theme.rule))


def widths(ws, first: float, others: float, n: int, extra: dict[str, float] | None = None) -> None:
    ws.column_dimensions["A"].width = first
    for i in range(2, n + 1):
        ws.column_dimensions[get_column_letter(i)].width = others
    for col, w in (extra or {}).items():
        ws.column_dimensions[col].width = w


def align_left(cell) -> None:
    cell.alignment = Alignment(horizontal="left")


def fill_assumption(cell) -> None:
    cell.fill = PatternFill("solid", start_color=_theme.assumption_fill)
