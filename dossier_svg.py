"""Small, self-contained SVG helpers used by the dossier artwork."""

from __future__ import annotations

import html
from pathlib import Path


ASSETS = Path(__file__).resolve().parent / "assets"
INK = "#202124"
MID = "#56585C"
WHITE = "#FFFFFF"


def text(x, y, value, size, fill=INK, weight=400, anchor="start", family="Helvetica Neue", tracking=0):
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'letter-spacing="{tracking}">{html.escape(str(value), quote=True)}</text>'
    )


def wrap(x, y, lines, size, fill=INK, line_height=None, weight=400, family="Helvetica Neue"):
    step = line_height or int(size * 1.38)
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if i == 0 else step}">{html.escape(str(line), quote=True)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="start">{spans}</text>'
    )


def svg(width, height, content):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{WHITE}"/>{content}</svg>'
    )
