#!/usr/bin/env python3
"""Create quick information-design mock-ups for the QualiBact species dossier."""

from __future__ import annotations

import base64
import html
import os
import re
import subprocess
from pathlib import Path

from PIL import ImageFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

from dossier_svg import ASSETS, INK, MID, WHITE, svg, text as plain_text, wrap


ROOT = Path(__file__).resolve().parent
MOCK = ROOT / "mockups" / "qualibact-dossier-v2"
CACHE = ROOT / "cache" / "qualibact" / "Escherichia_coli" / "qualibact-v1.0"
QR = CACHE / "species-page-qr.png"
PLOT_N50 = CACHE / "plots" / "Escherichia_coli_filt_N50_number.png"
PLOT_CDS = CACHE / "plots" / "Escherichia_coli_CDS_vs_Genome_Size.png"
PLOT_GC = CACHE / "plots" / "GC_Content_refseq_histogram_kde.png"

# Match the dominant purple in the official CGPS logo text.
PURPLE = "#683D90"
LAVENDER = "#F5F1FA"
RULE = "#D9D0E7"
WARN = "#A95F19"
FAIL = "#A32C3D"
PASS = "#2F6B5D"

SUMMARY = (
    "Usually a harmless gut commensal, this bacterium also has pathogenic variants "
    "that cause urinary tract infections, bacteraemia, neonatal meningitis and diarrhoeal disease. "
    "Its open pangenome is shaped by plasmids, phages and horizontal gene transfer, "
    "making it a critical sentinel for antimicrobial resistance surveillance."
)
SPECIES = "Escherichia coli"
SCHEME = "qualibact-v1.0"
GENOME_COUNT = 376_660
REFSEQ_COUNT = 5_033
SHOW_ENGINE_FLAG = True
ENGINE_FLAG = "WARN"
ENGINE_NOTE = "A small number of extreme outliers stretch the FAIL bounds. See the species-page flag before use."
PATHOGENWATCH_LINES = (
    "QualiBact QC, typing, AMR predictions,",
    "evolutionary relationships and more.",
)
METHODS_COPY = (
    "QualiBact filters anomalous assemblies with an Isolation Forest. "
    "Species-specific WARN and FAIL bounds come from the filtered pool. "
    "Complete RefSeq genomes also inform genome size and GC content."
)
LEFT_CAPTION_TITLE = "Filtered N50 vs number of contigs"
LEFT_CAPTION_COPY = (
    "Retained assemblies cluster toward fewer contigs and higher N50. "
    "Colour shows the Isolation Forest anomaly score in the plot legend."
)
GC_CAPTION_COPY = "SRA and RefSeq distributions reveal shifts, peaks and outliers."
RIGHT_CAPTION_TITLE = "CDS vs genome size"
RIGHT_CAPTION_COPY = (
    "Gene count generally rises with assembly size. "
    "Secondary trends may indicate sub-populations or residual contamination."
)
BODY_FAMILY = os.environ.get("QCD_BODY_FAMILY", "Avenir Next")
BODY_FONT_PATH = os.environ.get("QCD_BODY_FONT", "/System/Library/Fonts/Avenir Next.ttc")
BODY_FONT_SIZE = 21
SAIRA_FONT_PATH = os.environ.get(
    "QCD_SAIRA_FONT", str(ROOT / "fonts" / "SairaCondensed-SemiBold.ttf")
)
SAIRA_FONT = TTFont(SAIRA_FONT_PATH)
SAIRA_GLYPHS = SAIRA_FONT.getGlyphSet()
SAIRA_CMAP = SAIRA_FONT.getBestCmap()
SAIRA_UNITS = SAIRA_FONT["head"].unitsPerEm
SAIRA_PATHS: dict[str, str] = {}

THRESHOLDS = [
    ("Genome size", "4.1 Mb", "4.4 Mb", "5.7 Mb", "6.3 Mb"),
    ("GC content", "50.0%", "50.2%", "50.9%", "51.2%"),
    ("Coding sequences", "3,900", "4,200", "5,800", "6,500"),
    ("Completeness (CheckM2)", "95%", "100%", "—", "—"),
    ("Contamination (CheckM2)", "—", "—", "2%", "16%"),
    ("N50 (Shovill)", "20 kb", "23 kb", "—", "—"),
    ("Contigs (Shovill)", "—", "—", "600", "670"),
]


def saira_outline(
    x: float, y: float, value: str, size: int, fill: str,
    anchor: str = "start", tracking: float = 0, italic: bool = False,
) -> str:
    """Use the installed SemiBold outlines; librsvg substitutes SVG font-family names here."""
    font = ImageFont.truetype(SAIRA_FONT_PATH, size)
    advance = font.getlength(value) + max(0, len(value) - 1) * tracking
    origin = x - advance / 2 if anchor == "middle" else x - advance if anchor == "end" else x
    scale = size / SAIRA_UNITS
    glyphs = []
    for i, char in enumerate(value):
        glyph_name = SAIRA_CMAP.get(ord(char))
        if glyph_name is None:
            return plain_text(x, y, value, size, fill, 600, anchor, "Saira Condensed", tracking)
        if glyph_name not in SAIRA_PATHS:
            pen = SVGPathPen(SAIRA_GLYPHS)
            SAIRA_GLYPHS[glyph_name].draw(pen)
            SAIRA_PATHS[glyph_name] = pen.getCommands()
        path = SAIRA_PATHS[glyph_name]
        if path:
            offset = font.getlength(value[:i]) + i * tracking
            glyphs.append(f'<path d="{path}" transform="translate({offset:.3f} 0) scale({scale:.6f} {-scale:.6f})"/>')
    slant = " skewX(-12)" if italic else ""
    return (
        f'<g fill="{fill}" transform="translate({origin:.3f} {y:.3f}){slant}">'
        f'<title>{html.escape(value)}</title>{"".join(glyphs)}</g>'
    )


def text(x, y, value, size, fill=INK, weight=400, anchor="start", family=BODY_FAMILY, tracking=0, italic=False):
    if family.startswith("Saira Condensed"):
        return saira_outline(x, y, value, size, fill, anchor, tracking)
    if italic:
        return (
            f'<text x="{x}" y="{y}" fill="{fill}" font-family="{family}" '
            f'font-size="{size}" font-weight="{weight}" font-style="italic" '
            f'text-anchor="{anchor}" letter-spacing="{tracking}">{html.escape(value)}</text>'
        )
    return plain_text(x, y, value, size, fill, weight, anchor, family, tracking)


SCIENTIFIC_GENERA = {
    "Acinetobacter", "Campylobacter", "Enterobacter", "Enterococcus", "Escherichia",
    "Haemophilus", "Klebsiella", "Listeria", "Mycobacterium", "Neisseria",
    "Pseudomonas", "Renibacterium", "Salmonella", "Shigella", "Staphylococcus",
    "Stenotrophomonas", "Streptococcus", "Vibrio",
}


def italic_word_flags(words: list[str]) -> list[bool]:
    """Italicise Latin taxa in summary copy without storing SVG markup in the text."""
    clean = [re.sub(r"^[^A-Za-z]+|[^A-Za-z.-]+$", "", word) for word in words]
    flags = [False] * len(words)
    for i, word in enumerate(clean):
        if word in SCIENTIFIC_GENERA:
            flags[i] = True
            if i + 1 < len(words) and re.fullmatch(r"[a-z][a-z-]+", clean[i + 1]) \
                    and clean[i + 1] not in {"species", "complex", "strains", "lineages"}:
                flags[i + 1] = True
        elif re.fullmatch(r"[A-Z]\.", word) and i + 1 < len(words) \
                and re.fullmatch(r"[a-z][a-z-]+", clean[i + 1]):
            flags[i] = flags[i + 1] = True
        elif word in {"equi", "zooepidemicus"} and i and clean[i - 1].lower() in {"subspecies", "subsp."}:
            flags[i] = True
    return flags


def image(path: Path, x: int, y: int, w: int, h: int, fit: str = "meet") -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return (
        f'<image x="{x}" y="{y}" width="{w}" height="{h}" '
        f'preserveAspectRatio="xMidYMid {fit}" href="data:image/png;base64,{data}"/>'
    )


def logo(x: int = 72, y: int = 46, w: int = 320, h: int = 78) -> str:
    return image(ASSETS / "cgps-logo.png", x, y, w, h)


def top_identity(page: str | None = None) -> str:
    p = [f'<rect x="0" y="0" width="1080" height="16" fill="{PURPLE}"/>', logo()]
    p.append('<rect x="650" y="58" width="206" height="58" rx="3" fill="none" stroke="#6B6273" stroke-width="1.5"/>')
    p.append(text(668, 82, "Genome QC dossier", 17, INK, 650, tracking=0.2))
    p.append(text(668, 103, "QualiBact", 15, MID, 500))
    if page:
        p.append(text(840, 103, page, 15, MID, 600, "end"))
    p.append(image(QR, 885, 38, 124, 124))
    p.append(text(947, 184, "Open species page", 13, MID, 500, "middle"))
    return "".join(p)


def species_title(y: int = 228) -> str:
    return saira_outline(72, y, SPECIES, 76, PURPLE, italic=True)


def panel_rect(x: int, y: int, width: int, height: int) -> str:
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="5" fill="{PURPLE}"/>'


def measured_lines(copy: str, width: int, size: int) -> list[str]:
    font = ImageFont.truetype(BODY_FONT_PATH, size)
    lines: list[str] = []
    current: list[str] = []
    for word in copy.split():
        candidate = " ".join([*current, word])
        if current and font.getlength(candidate) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def justified_panel_copy(
    copy: str, y: int, h: int, x: int, width: int, size: int, line_height: int,
    letter_share: float = 0.9,
) -> str:
    """Position words explicitly: librsvg ignores SVG textLength justification."""
    font = ImageFont.truetype(BODY_FONT_PATH, size)
    lines = measured_lines(copy, width, size)
    first_baseline = y + (h - len(lines) * line_height) / 2 + size + 3
    rendered = []
    for row, complete_line in enumerate(lines):
        baseline = first_baseline + row * line_height
        words = complete_line.split()
        italics = italic_word_flags(words)
        if row == len(lines) - 1:
            if not any(italics):
                rendered.append(text(x, baseline, complete_line, size, WHITE, 500, family=BODY_FAMILY))
            else:
                cursor = float(x)
                for word, italic in zip(words, italics):
                    rendered.append(text(cursor, baseline, word, size, WHITE, 500,
                                         family=BODY_FAMILY, italic=italic))
                    cursor += font.getlength(word + " ")
            continue
        space_width = font.getlength(" ")
        word_widths = [font.getlength(word) for word in words]
        space_count = len(words) - 1
        letter_count = sum(len(word) - 1 for word in words)
        extra = width - (sum(word_widths) + space_count * space_width)
        letter_spacing = letter_share * extra / letter_count
        word_spacing = space_width + (1 - letter_share) * extra / space_count
        if letter_spacing > 1.3:
            if not any(italics):
                rendered.append(text(x, baseline, complete_line, size, WHITE, 500, family=BODY_FAMILY))
            else:
                cursor = float(x)
                for word, italic in zip(words, italics):
                    rendered.append(text(cursor, baseline, word, size, WHITE, 500,
                                         family=BODY_FAMILY, italic=italic))
                    cursor += font.getlength(word + " ")
            continue
        cursor = float(x)
        for index, word in enumerate(words):
            if index == len(words) - 1:
                rendered.append(text(x + width, baseline, word, size, WHITE, 500, "end", BODY_FAMILY,
                                     letter_spacing, italic=italics[index]))
            else:
                rendered.append(text(cursor, baseline, word, size, WHITE, 500,
                                     family=BODY_FAMILY, tracking=letter_spacing, italic=italics[index]))
                cursor += word_widths[index] + (len(word) - 1) * letter_spacing + word_spacing
    return "".join(rendered)


def summary_box(y: int, h: int = 174) -> str:
    return (
        panel_rect(72, y, 936, h)
        + justified_panel_copy(SUMMARY, y, h, 102, 876, BODY_FONT_SIZE, 31)
    )


def evidence_line(y: int, show_flag: bool = True) -> str:
    result = (
        text(72, y, f"Quality control thresholds derived from {GENOME_COUNT:,} genomes", 19, INK, 650)
        + text(72, y + 25, f"Including {REFSEQ_COUNT:,} RefSeq reference genomes", 15, MID, 500)
    )
    if show_flag:
        result += (
            f'<rect x="858" y="{y - 27}" width="150" height="44" rx="22" fill="#FFF3D6"/>'
            + text(933, y + 1, "Engine flag: WARN", 15, WARN, 700, "middle")
        )
    return result


def flag_note() -> str:
    if not SHOW_ENGINE_FLAG:
        return ""
    flag_fill = {"ERROR": "#FCE7EB", "WARN": "#FFF3D6", "INFO": LAVENDER}[ENGINE_FLAG]
    flag_ink = {"ERROR": FAIL, "WARN": WARN, "INFO": PURPLE}[ENGINE_FLAG]
    return (
        f'<rect x="72" y="1151" width="160" height="44" rx="22" fill="{flag_fill}"/>'
        + text(152, 1179, f"Engine flag: {ENGINE_FLAG}", 15, flag_ink, 700, "middle")
        + text(248, 1179, ENGINE_NOTE, 16, MID, 450, family=BODY_FAMILY)
    )


def pathogenwatch_callout() -> str:
    return (
        f'<circle cx="678" cy="467" r="11" fill="{PURPLE}"/>'
        '<path d="M673 467 l4 4 7 -8" fill="none" stroke="white" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        + text(702, 474, "Pathogenwatch supported", 19, PURPLE, 650)
        + text(702, 499, PATHOGENWATCH_LINES[0], 16, MID, 450, family=BODY_FAMILY)
        + text(702, 521, PATHOGENWATCH_LINES[1], 16, MID, 450, family=BODY_FAMILY)
    )


def threshold_table(y: int, row_h: int = 43, compact: bool = False) -> str:
    x0, w = 72, 936
    cols = [0, 286, 448, 610, 772, 936]
    header_h = 52
    total_h = header_h + len(THRESHOLDS) * row_h
    p = [f'<rect x="{x0}" y="{y}" width="{w}" height="{total_h}" fill="{WHITE}" stroke="{RULE}"/>']
    p.append(f'<rect x="{x0}" y="{y}" width="{w}" height="{header_h}" fill="{LAVENDER}"/>')
    headers = [("Metric", INK), ("Fail below", FAIL), ("Warn below", WARN), ("Warn above", WARN), ("Fail above", FAIL)]
    for i, (label, colour) in enumerate(headers):
        anchor = "start" if i == 0 else "middle"
        tx = x0 + cols[i] + 14 if i == 0 else x0 + (cols[i] + cols[i + 1]) / 2
        p.append(text(tx, y + 33, label, 16 if compact else 18, colour, 700, anchor))
    for i, row in enumerate(THRESHOLDS):
        ry = y + header_h + i * row_h
        if i % 2:
            p.append(f'<rect x="{x0}" y="{ry}" width="{w}" height="{row_h}" fill="#FBFAFC"/>')
        p.append(f'<line x1="{x0}" y1="{ry}" x2="{x0+w}" y2="{ry}" stroke="{RULE}" stroke-width="1"/>')
        p.append(text(x0 + 14, ry + row_h * 0.67, row[0], 15 if compact else 18, INK, 600))
        for j, value in enumerate(row[1:]):
            tx = x0 + (cols[j + 1] + cols[j + 2]) / 2
            colour = FAIL if j in (0, 3) and value != "—" else WARN if value != "—" else MID
            p.append(text(tx, ry + row_h * 0.67, value, 15 if compact else 19, colour, 600, "middle"))
    return "".join(p)


def verdict_key(y: int) -> str:
    p = [text(72, y, "How to read the table", 18, INK, 650)]
    items = [
        (PASS, "PASS", "between the Warn bounds"),
        (WARN, "WARN", "between Warn and Fail"),
        (FAIL, "FAIL", "outside the Fail bounds"),
    ]
    x = 72
    for colour, label, desc in items:
        p.append(f'<circle cx="{x + 7}" cy="{y + 29}" r="7" fill="{colour}"/>')
        p.append(text(x + 22, y + 35, label, 14, INK, 700))
        p.append(text(x + 68, y + 35, desc, 14, MID, 450))
        x += 302
    return "".join(p)


def verdict_dots(y: int) -> str:
    p = []
    items = (
        (72, PASS, "PASS", "between the Warn bounds", 95),
        (380, WARN, "WARN", "between Warn and Fail", 110),
        (688, FAIL, "FAIL", "outside the Fail bounds", 90),
    )
    for x, colour, label, explanation, explanation_offset in items:
        p.append(f'<circle cx="{x + 8}" cy="{y}" r="8" fill="{colour}"/>')
        p.append(text(x + 28, y + 6, label, 17, INK, 700))
        p.append(text(x + explanation_offset, y + 6, explanation, 16, MID, 450, family=BODY_FAMILY))
    return "".join(p)


def footer(message: str = "See this and 300+ species at qualibact.org") -> str:
    y = 1250
    return (
        f'<rect x="0" y="{y}" width="1080" height="100" fill="{PURPLE}"/>'
        + text(72, y + 62, message, 29, WHITE, 650, family="Saira Condensed")
        + text(1008, y + 62, "Analyse your genomes at pathogen.watch", 29, WHITE, 650, "end", "Saira Condensed")
    )


def direction_a() -> str:
    p = [top_identity(), species_title(), summary_box(252, 168), evidence_line(460)]
    p.append(text(72, 525, "Published PASS / WARN / FAIL thresholds", 23, INK, 700))
    p.append(threshold_table(546, 39, compact=True))
    p.append(verdict_key(923))
    p.append(text(72, 1006, "One diagnostic view", 20, INK, 700))
    p.append(image(PLOT_N50, 72, 1022, 360, 205))
    p.append(text(460, 1055, "Filtered assemblies: N50 vs number of contigs", 16, INK, 650))
    p.append(wrap(460, 1084, [
        "The retained genomes cluster toward fewer contigs and higher N50.",
        "Colour encodes the Isolation Forest anomaly score shown in the plot legend.",
        "Published bounds may differ slightly after rounding and curator adjustment.",
    ], 14, MID, 22, 450, BODY_FAMILY))
    p.append(footer())
    return svg(1080, 1350, "".join(p))


def band(x: int, y: int, label: str, fail_l: str, warn_l: str, warn_h: str, fail_h: str) -> str:
    p = [text(x, y, label, 16, INK, 650)]
    sy = y + 20
    p.append(f'<rect x="{x}" y="{sy}" width="812" height="22" rx="11" fill="#F4DCE0"/>')
    p.append(f'<rect x="{x+120}" y="{sy}" width="572" height="22" fill="#F7E8D4"/>')
    p.append(f'<rect x="{x+250}" y="{sy}" width="312" height="22" fill="#DDEDE8"/>')
    labels = [(x, fail_l, "start"), (x+120, warn_l, "middle"), (x+692, warn_h, "middle"), (x+812, fail_h, "end")]
    for lx, value, anchor in labels:
        p.append(text(lx, sy + 47, value, 13, MID, 600, anchor))
    return "".join(p)


def direction_b() -> str:
    p = [top_identity(), species_title(), summary_box(252, 168), evidence_line(460)]
    p.append(text(72, 525, "Threshold bands at a glance", 23, INK, 700))
    p.append(text(1008, 525, "FAIL   WARN   PASS   WARN   FAIL", 13, MID, 650, "end"))
    p.append(band(96, 563, "Genome size", "4.1 Mb", "4.4 Mb", "5.7 Mb", "6.3 Mb"))
    p.append(band(96, 653, "GC content", "50.0%", "50.2%", "50.9%", "51.2%"))
    p.append(band(96, 743, "Coding sequences", "3,900", "4,200", "5,800", "6,500"))
    p.append(band(96, 833, "N50 (lower bound only)", "20 kb", "23 kb", "PASS above", "—"))
    p.append(text(72, 930, "Evidence views", 21, INK, 700))
    p.append(image(PLOT_N50, 72, 950, 430, 230))
    p.append(image(PLOT_GC, 566, 950, 442, 200))
    p.append(text(72, 1194, "N50 vs contigs · filtered genomes", 15, INK, 650))
    p.append(text(566, 1168, "GC content · SRA compared with RefSeq", 15, INK, 650))
    p.append(footer())
    return svg(1080, 1350, "".join(p))


def direction_c_thresholds() -> str:
    p = [top_identity("1 / 2"), species_title(), summary_box(252, 182), evidence_line(475, show_flag=False)]
    p.append(text(72, 524, f"Rounded values · {SCHEME}", 14, MID, 550))
    p.append(pathogenwatch_callout())
    p.append(threshold_table(541, 69))
    p.append(verdict_dots(1121))
    p.append(flag_note())
    p.append(footer())
    return svg(1080, 1350, "".join(p))


def caption(x: int, y: int, width: int, title_line: str, copy: str) -> str:
    """Keep figure explanations within the width of their respective plots."""
    lines = measured_lines(copy, width - 24, 16)
    return text(x, y, title_line, 21, INK, 700) + wrap(x, y + 29, lines, 16, MID, 24, 450, BODY_FAMILY)


def direction_c_evidence() -> str:
    p = [top_identity("2 / 2")]
    p.append(text(72, 224, "Methods and evidence", 48, PURPLE, 400, family="Saira Condensed SemiBold"))
    p.append(
        f'<text x="72" y="260" fill="{MID}" font-family="{BODY_FAMILY}" font-size="18" font-weight="500">'
        f'<tspan font-style="italic">{html.escape(SPECIES)}</tspan><tspan> · {html.escape(SCHEME)}</tspan></text>'
    )
    p.append(panel_rect(72, 292, 566, 132))
    p.append(justified_panel_copy(
        METHODS_COPY,
        292, 132, 102, 506, 18, 26, letter_share=0.45,
    ))
    p.append(image(PLOT_N50, 72, 444, 566, 566))
    p.append(caption(72, 1042, 566, LEFT_CAPTION_TITLE, LEFT_CAPTION_COPY))
    p.append(f'<line x1="656" y1="292" x2="656" y2="1130" stroke="{RULE}" stroke-width="1"/>')
    p.append(image(PLOT_CDS, 674, 292, 334, 250))
    p.append(caption(674, 574, 334, RIGHT_CAPTION_TITLE, RIGHT_CAPTION_COPY))
    p.append(f'<line x1="674" y1="700" x2="1008" y2="700" stroke="{RULE}" stroke-width="1"/>')
    p.append(image(PLOT_GC, 674, 752, 334, 250))
    p.append(caption(674, 1042, 334, "GC-content distribution", GC_CAPTION_COPY))
    p.append(footer())
    return svg(1080, 1350, "".join(p))


def main() -> None:
    MOCK.mkdir(parents=True, exist_ok=True)
    outputs = {
        "direction-a-reference-first": direction_a(),
        "direction-b-threshold-bands": direction_b(),
        "direction-c1-carousel-thresholds": direction_c_thresholds(),
        "direction-c2-carousel-evidence": direction_c_evidence(),
    }
    pngs: list[Path] = []
    for name, content in outputs.items():
        svg_path = MOCK / f"{name}.svg"
        png_path = MOCK / f"{name}.png"
        svg_path.write_text(content, encoding="utf-8")
        subprocess.run(["rsvg-convert", "-w", "1080", "-h", "1350", str(svg_path), "-o", str(png_path)], check=True)
        pngs.append(png_path)
    subprocess.run([
        "montage", *map(str, pngs), "-thumbnail", "432x540", "-tile", "4x1", "-geometry", "+24+24",
        "-background", "#EEEAF3", str(MOCK / "comparison.png"),
    ], check=True)


if __name__ == "__main__":
    main()
