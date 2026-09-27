#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11", "fonttools>=4", "qrcode[pil]>=8"]
# ///
"""Render the approved, fixed-type two-page QualiBact dossier.

The E. coli artwork is the golden layout. Other species use the same positions,
type sizes and plot frames. Missing source material and text overflow are errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from PIL import ImageFont
import qrcode

import make_qualibact_dossier_mockups as art


ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "qualibact"
OUTPUT = ROOT / "output" / "qualibact-dossiers"
SUMMARY_LIMIT = len(art.SUMMARY)  # approved E. coli copy: the longest permitted
APPROVED_ECOLI_SUMMARY = art.SUMMARY
TITLE_SIZE = 76
TITLE_MAX_WIDTH = 936
SUMMARY_MAX_LINES = 4
SUMMARY_MIN_LINES = 2
SUMMARY_FONT_SIZE = 21
SUMMARY_WIDTH = 876
SUPPORTED_SOURCE = "https://pathogen.watch/supported-organisms"

# Names transcribed from the live supported-organisms table on 27 September 2026.
# This is an eligibility gate, not a claim that every name has a QualiBact dossier.
PATHOGENWATCH_NAMES = frozenset("""
Campylobacter coli|Campylobacter jejuni|Enterobacter cloacae complex|
Escherichia coli|Klebsiella aerogenes|Klebsiella africana|
Klebsiella grimontii|Klebsiella huaxiensis|Klebsiella michiganensis|
Klebsiella oxytoca|Klebsiella pasteurii|Klebsiella pneumoniae|
Klebsiella quasipneumoniae|Klebsiella quasivariicola|
Klebsiella spallanzanii|Klebsiella variicola|Salmonella enterica|
Salmonella Enteritidis|Salmonella Typhi|Salmonella Typhimurium|
Shigella flexneri|Shigella sonnei|Enterococcus faecium|
Listeria monocytogenes|Stenotrophomonas maltophilia|
Renibacterium salmoninarum|Acinetobacter baumannii|
Mycobacterium abscessus|Mycobacterium tuberculosis|
Neisseria gonorrhoeae|Neisseria meningitidis|Haemophilus influenzae|
Pseudomonas aeruginosa|Staphylococcus aureus|Streptococcus equi|
Streptococcus pneumoniae|Vibrio cholerae|Candida auris|SARS-CoV-2|
Zika virus
""".replace("\n", "").split("|"))
EXCLUDE = frozenset({
    "Salmonella Enteritidis", "Salmonella Typhi", "Salmonella Typhimurium",
    "Shigella flexneri", "Shigella sonnei", "Candida auris",
    "SARS-CoV-2", "Zika virus",
})
SPECIES_MAPPING = {"Enterobacter cloacae complex": "Enterobacter cloacae"}


def species_page_url(species: str) -> str:
    words = species.split()
    if len(words) != 2:
        raise ValueError(f"{species}: no exact binomial QualiBact dossier mapping; review manually")
    return f"https://qualibact.org/{words[0]}/{'_'.join(words)}/"


def engine_quality_flag(page_html: str) -> str | None:
    parser = OverviewParser()
    parser.feed(page_html)
    match = re.search(r"Engine quality flag:\s*([A-Za-z]+)", parser.text, re.IGNORECASE)
    if not match:
        return None
    flag = match.group(1).upper()
    if flag not in {"INFO", "WARN", "ERROR"}:
        raise ValueError(f"Unknown QualiBact engine quality flag: {flag}")
    return flag


def eligible_species(species: set[str], refresh: bool) -> tuple[list[str], dict[str, str]]:
    approved = []
    error_exclusions = {}
    for name in sorted(species):
        slug = name.replace(" ", "_")
        page = source_bytes(species_page_url(name), CACHE / slug / "page.html", refresh)
        if engine_quality_flag(page.decode("utf-8", errors="replace")) == "ERROR":
            error_exclusions[name] = species_page_url(name)
        else:
            approved.append(name)
    return approved, error_exclusions


class OverviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_h1 = False
        self.heading = ""
        self.want_paragraph = False
        self.in_paragraph = False
        self.description = ""
        self.text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            self.in_h1 = True
            self.heading = ""
        elif tag == "p" and self.want_paragraph and not self.description:
            self.in_paragraph = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.in_h1:
            self.want_paragraph = self.heading.strip().endswith("QC Overview")
            self.in_h1 = False
        elif tag == "p" and self.in_paragraph:
            self.in_paragraph = False
            self.want_paragraph = False

    def handle_data(self, data: str) -> None:
        if self.in_h1:
            self.heading += data
        if self.in_paragraph:
            self.description += data
        self.text += " " + data


class PublishedTableParser(HTMLParser):
    """Read the first table following the species page's published-threshold heading."""

    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.cell_text = ""
        self.row: list[str] = []
        self.rows: list[list[str]] = []
        self.finished = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.finished:
            return
        if tag in ("td", "th"):
            self.in_cell = True
            self.cell_text = ""
        elif tag == "tr":
            self.row = []

    def handle_endtag(self, tag: str) -> None:
        if self.finished:
            return
        if tag in ("td", "th") and self.in_cell:
            self.row.append(" ".join(self.cell_text.split()))
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
        elif tag == "table":
            self.finished = True

    def handle_data(self, data: str) -> None:
        if self.in_cell and not self.finished:
            self.cell_text += data


class SpeciesIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.href: str | None = None
        self.name = ""
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.name = ""

    def handle_data(self, data: str) -> None:
        if self.href:
            self.name += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            name = " ".join(self.name.split())
            if re.fullmatch(r"/[A-Z][A-Za-z]+/[A-Z][A-Za-z]+_[a-z][A-Za-z-]+/?", self.href):
                self.names.add(name)
            self.href = None


def qualibact_species(refresh: bool) -> set[str]:
    url = "https://qualibact.org/species/"
    page = source_bytes(url, CACHE / "species-index.html", refresh).decode("utf-8", errors="replace")
    parser = SpeciesIndexParser()
    parser.feed(page)
    if len(parser.names) < 300:
        raise ValueError(f"QualiBact index parser found only {len(parser.names)} species; source layout may have changed")
    return parser.names


def source_bytes(url: str, path: Path, refresh: bool) -> bytes:
    if path.exists() and not refresh:
        return path.read_bytes()
    if os.environ.get("QCD_OFFLINE") == "1":
        raise FileNotFoundError(f"Offline source missing: {path}; run download_qualibact_data.py first")
    request = urllib.request.Request(url, headers={"User-Agent": "CGPS-dossier/1.0"})
    with urllib.request.urlopen(request, timeout=40) as response:
        data = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def scheme_from_page(text: str) -> str:
    import re
    match = re.search(r"Preferred scheme:\s*([\w.-]+)", text)
    if not match:
        raise ValueError("QualiBact page does not identify a preferred QC scheme")
    return match.group(1)


def summary_for(species: str, description: str, overrides: dict[str, str]) -> str:
    if species in overrides:
        return " ".join(overrides[species].split())
    if species == "Escherichia coli":
        return APPROVED_ECOLI_SUMMARY
    source = " ".join(description.split())
    prefix = species + " is "
    if source.startswith(prefix):
        source = source[len(prefix):]
        source = source[:1].upper() + source[1:]
    # Keep complete source sentences only. Never truncate inside a claim.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", source)
    selected = ""
    for sentence in sentences:
        candidate = f"{selected} {sentence}".strip()
        if len(candidate) > SUMMARY_LIMIT or len(art.measured_lines(candidate, SUMMARY_WIDTH, SUMMARY_FONT_SIZE)) > SUMMARY_MAX_LINES:
            break
        selected = candidate
    return selected


def validate_copy(species: str, summary: str) -> None:
    if not summary:
        raise ValueError(f"{species}: empty summary")
    lines = art.measured_lines(summary, SUMMARY_WIDTH, SUMMARY_FONT_SIZE)
    if len(summary) > SUMMARY_LIMIT or len(lines) > SUMMARY_MAX_LINES or len(lines) < SUMMARY_MIN_LINES:
        raise ValueError(
            f"{species}: summary is {len(summary)} characters / {len(lines)} lines; "
            f"approved range is {SUMMARY_MIN_LINES}–{SUMMARY_MAX_LINES} lines, "
            f"up to {SUMMARY_LIMIT} characters. "
            "Edit a source-grounded summary; the type will not shrink or clip."
        )
    body_font = ImageFont.truetype(art.BODY_FONT_PATH, SUMMARY_FONT_SIZE)
    if any(body_font.getlength(line) > SUMMARY_WIDTH for line in lines):
        raise ValueError(f"{species}: a summary line exceeds the fixed panel width")
    if body_font.getlength(lines[-1]) < 200:
        raise ValueError(f"{species}: short orphan line in the summary panel")
    title_width = ImageFont.truetype(art.SAIRA_FONT_PATH, TITLE_SIZE).getlength(species)
    if title_width > TITLE_MAX_WIDTH:
        raise ValueError(f"{species}: title exceeds the fixed {TITLE_MAX_WIDTH}px frame")
    if len(art.measured_lines(f"Quality control thresholds derived from {art.GENOME_COUNT:,} genomes", 560, 19)) > 1:
        raise ValueError(f"{species}: genome-count label exceeds its fixed frame")
    label_font = ImageFont.truetype(art.BODY_FONT_PATH, 18)
    value_font = ImageFont.truetype(art.BODY_FONT_PATH, 19)
    for row in art.THRESHOLDS:
        if label_font.getlength(row[0]) > 258:
            raise ValueError(f"{species}: table metric label exceeds its fixed cell: {row[0]}")
        for value in row[1:]:
            if value_font.getlength(value) > 148:
                raise ValueError(f"{species}: table value exceeds its fixed cell: {value}")


def fmt_published(metric: str, value: str) -> str:
    if value in ("-", "—", ""):
        return "—"
    numeric = float(value.replace(",", ""))
    if metric == "Genome_Size":
        return f"{numeric / 1_000_000:.1f} Mb"
    if metric == "GC_Content":
        return f"{numeric:.1f}%"
    if metric in ("Completeness_Specific", "Contamination"):
        return f"{numeric:g}%"
    if metric == "N50":
        return f"{numeric / 1_000:g} kb"
    return f"{numeric:,.0f}"


METRICS = (
    ("Genome_Size", "Genome size"),
    ("GC_Content", "GC content"),
    ("Total_Coding_Sequences", "Coding sequences"),
    ("Completeness_Specific", "Completeness (CheckM2)"),
    ("Contamination", "Contamination (CheckM2)"),
    ("N50", "N50 (Shovill)"),
    ("no_of_contigs", "Contigs (Shovill)"),
)


def table_rows(species: str, page_html: str) -> list[tuple[str, str, str, str, str]]:
    heading = page_html.find("Suggested thresholds for")
    if heading < 0:
        raise ValueError(f"{species}: no published thresholds heading on species page")
    table_start = page_html.find("<table", heading)
    if table_start < 0:
        raise ValueError(f"{species}: no published threshold table on species page")
    parser = PublishedTableParser()
    parser.feed(page_html[table_start:])
    if not parser.finished:
        raise ValueError(f"{species}: published table did not parse completely")
    raw = {row[0]: row[1:] for row in parser.rows[1:] if len(row) == 5}
    missing = [key for key, _ in METRICS if key not in raw]
    if missing:
        raise ValueError(f"{species}: missing published threshold metrics: {', '.join(missing)}")
    rows = []
    for key, label in METRICS:
        rows.append((label, *(fmt_published(key, value) for value in raw[key])))
    return rows


def qr_for(url: str, path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(path)


def plot_paths(species: str, slug: str, scheme: str, manifest: dict) -> tuple[str, str, str, bool]:
    plots = manifest.get("plots", {})
    n50 = next((name for name in manifest.get("filtered_plot_files", [])
                if name.endswith("_filt_N50_number.png")), None)
    if n50:
        left = f"{slug}/{scheme}/filtered_plots/{n50}"
    elif scheme == "REFSEQ-QC-v1":
        left = plots.get("Genome_Size", {}).get("histogram_kde")
    else:
        raise ValueError(f"{species}: required filtered N50 vs contigs plot is absent")
    right = plots.get("CDS_vs_Genome_Size") or plots.get("Genome_Size", {}).get("histogram_kde")
    gc = plots.get("GC_Content", {}).get("histogram_kde")
    if not all((left, right, gc)):
        raise ValueError(f"{species}: one or more required source plots are absent")
    return left, right, gc, bool(n50)


def build(species: str, refresh: bool, overrides: dict[str, str], preflight: bool = False) -> tuple[Path, Path] | None:
    if species in EXCLUDE:
        raise ValueError(f"{species}: excluded by the approved dossier scope")
    if species not in PATHOGENWATCH_NAMES and species not in SPECIES_MAPPING.values():
        raise ValueError(f"{species}: not on the approved Pathogenwatch-to-QualiBact list")
    words = species.split()
    page_url = species_page_url(species)
    slug = "_".join(words)
    page = source_bytes(page_url, CACHE / slug / "page.html", refresh).decode("utf-8", errors="replace")
    flag = engine_quality_flag(page)
    if flag == "ERROR":
        raise ValueError(f"{species}: engine quality flag ERROR; dossier generation is prohibited ({page_url})")
    parser = OverviewParser()
    parser.feed(page)
    if not parser.description:
        raise ValueError(f"{species}: no QualiBact QC overview at {page_url}")
    scheme = scheme_from_page(parser.text)
    methods_by_scheme = {
        "qualibact-v1.0": (
            "QualiBact filters anomalous assemblies with an Isolation Forest. "
            "Species-specific WARN and FAIL bounds come from the filtered pool. "
            "Complete RefSeq genomes also inform genome size and GC content."
        ),
        "qualibact-v1.1": (
            "The v1.1 scheme uses the same outlier filtering and statistical pipeline as v1.0, "
            "with added reference genomes or expert revisions for this species. "
            "The published WARN and FAIL bounds are shown here."
        ),
        "REFSEQ-QC-v1": (
            "This scheme assesses reference-grade genomes with assembly statistics and CheckM2. "
            "Simulated short reads and Shovill are used where enabled. "
            "Published species-specific WARN and FAIL bounds are shown here."
        ),
    }
    if scheme not in methods_by_scheme:
        raise ValueError(f"{species}: unreviewed QC scheme {scheme}")
    art.METHODS_COPY = methods_by_scheme[scheme]
    if len(art.measured_lines(art.METHODS_COPY, 506, 18)) > 4:
        raise ValueError(f"{species}: {scheme} methods copy exceeds the fixed panel")
    cache = CACHE / slug / scheme
    manifest_url = f"https://static.qualibact.org/static/species/{slug}/{scheme}/manifest.json"
    manifest = json.loads(source_bytes(manifest_url, cache / "manifest.json", refresh))
    if not manifest.get("thresholds"):
        raise ValueError(f"{species}: no threshold table in QualiBact manifest")
    if manifest.get("scheme") != scheme:
        raise ValueError(f"{species}: page and manifest QC schemes disagree")

    art.SPECIES = species
    art.SCHEME = scheme
    art.SUMMARY = summary_for(species, parser.description, overrides)
    counts = manifest.get("counts", {})
    art.REFSEQ_COUNT = int(counts.get("refseq_count", 0))
    art.GENOME_COUNT = int(counts.get("genome_count", 0)) + art.REFSEQ_COUNT
    art.THRESHOLDS = table_rows(species, page)
    art.SHOW_ENGINE_FLAG = flag is not None
    art.ENGINE_FLAG = flag or ""
    art.ENGINE_NOTE = (
        "A small number of extreme outliers stretch the FAIL bounds. See the species-page flag before use."
        if species == "Escherichia coli" else
        "Reference genomes may include misclassified K. pasteurii; see the species-page note."
        if species == "Klebsiella grimontii" else
        "The reference set was flagged. Review the species-page quality note before use."
    )
    if species == "Escherichia coli":
        art.PATHOGENWATCH_LINES = (
            "QualiBact QC, typing, AMR predictions,",
            "evolutionary relationships and more.",
        )
    else:
        art.PATHOGENWATCH_LINES = (
            "QC and organism-specific analysis at",
            "pathogen.watch.",
        )
    validate_copy(species, art.SUMMARY)
    for line in art.PATHOGENWATCH_LINES:
        width = ImageFont.truetype(art.BODY_FONT_PATH, 16).getlength(line)
        if width > 306:
            raise ValueError(f"{species}: Pathogenwatch callout exceeds right margin")

    left_plot, cds_plot, gc_plot, has_filtered_n50 = plot_paths(species, slug, scheme, manifest)
    if has_filtered_n50:
        art.LEFT_CAPTION_TITLE = "Filtered N50 vs number of contigs"
        art.LEFT_CAPTION_COPY = (
            "Retained assemblies cluster toward fewer contigs and higher N50. "
            "Colour shows the Isolation Forest anomaly score in the plot legend."
        )
        art.GC_CAPTION_COPY = "SRA and RefSeq distributions reveal shifts, peaks and outliers."
    elif scheme == "REFSEQ-QC-v1":
        art.LEFT_CAPTION_TITLE = "Genome-size distribution"
        art.LEFT_CAPTION_COPY = (
            "The source reference assemblies define the observed genome-size range. "
            "Read this distribution alongside the published QC bounds."
        )
        art.GC_CAPTION_COPY = "Reference-genome GC content shows the observed range and outliers."
    if manifest.get("plots", {}).get("CDS_vs_Genome_Size"):
        art.RIGHT_CAPTION_TITLE = "CDS vs genome size"
        art.RIGHT_CAPTION_COPY = (
            "Each point is a source reference assembly. Interpret patterns cautiously when the set is small."
            if scheme == "REFSEQ-QC-v1" else
            "Gene count generally rises with assembly size. "
            "Secondary trends may indicate sub-populations or residual contamination."
        )
    else:
        art.RIGHT_CAPTION_TITLE = "Genome-size distribution"
        art.RIGHT_CAPTION_COPY = (
            "The genome-size distribution provides context for the published QC bounds."
        )
    paths = (
        ("PLOT_N50", left_plot),
        ("PLOT_CDS", cds_plot),
        ("PLOT_GC", gc_plot),
    )
    for attribute, relative_url in paths:
        if not relative_url:
            raise ValueError(f"{species}: required {attribute} plot is absent")
    if preflight:
        return None

    art.QR = cache / "species-page-qr.png"
    qr_for(page_url, art.QR)
    for attribute, relative_url in paths:
        if not relative_url:
            raise ValueError(f"{species}: required {attribute} plot is absent")
        target = cache / "plots" / Path(relative_url).name
        encoded = urllib.parse.quote(relative_url, safe="/")
        source_bytes(f"https://static.qualibact.org/static/species/{encoded}", target, refresh)
        setattr(art, attribute, target)

    destination = OUTPUT / slug
    destination.mkdir(parents=True, exist_ok=True)
    rendered = []
    for name, content in (
        ("01-thresholds", art.direction_c_thresholds()),
        ("02-evidence", art.direction_c_evidence()),
    ):
        svg = destination / f"{name}.svg"
        png = destination / f"{name}.png"
        svg.write_text(content, encoding="utf-8")
        subprocess.run(["rsvg-convert", "-w", "1080", "-h", "1350", str(svg), "-o", str(png)], check=True)
        rendered.append(png)
    (destination / "provenance.json").write_text(json.dumps({
        "species": species, "supported_organisms": SUPPORTED_SOURCE,
        "qualibact_page": page_url, "manifest": manifest_url,
        "scheme": scheme, "summary": art.SUMMARY,
        "summary_characters": len(art.SUMMARY), "summary_max_characters": SUMMARY_LIMIT,
        "genome_count": art.GENOME_COUNT, "refseq_count": art.REFSEQ_COUNT,
        "published_thresholds": art.THRESHOLDS,
        "engine_flag": art.ENGINE_FLAG if art.SHOW_ENGINE_FLAG else None,
        "plot_urls": [f"https://static.qualibact.org/static/species/{urllib.parse.quote(path, safe='/')}"
                      for _, path in paths],
        "captions": {
            "left": [art.LEFT_CAPTION_TITLE, art.LEFT_CAPTION_COPY],
            "right_top": [art.RIGHT_CAPTION_TITLE, art.RIGHT_CAPTION_COPY],
            "right_bottom": ["GC-content distribution", art.GC_CAPTION_COPY],
        },
    }, indent=2) + "\n", encoding="utf-8")
    (destination / "alt-text.txt").write_text(
        f"Page 1: {species} genome QC dossier. {art.SUMMARY} "
        f"Published QualiBact {scheme} FAIL and WARN thresholds for seven assembly metrics, "
        f"derived from {art.GENOME_COUNT:,} genomes.\n"
        f"Page 2: {species} methods and evidence. "
        f"Figures: {art.LEFT_CAPTION_TITLE}; {art.RIGHT_CAPTION_TITLE}; GC-content distribution.\n",
        encoding="utf-8",
    )
    return rendered[0], rendered[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("species", nargs="*", help="Exact binomial name shown by Pathogenwatch")
    parser.add_argument("--refresh", action="store_true", help="Reload QualiBact source data")
    parser.add_argument("--summaries", type=Path, default=ROOT / "dossier_summaries.json",
                        help="JSON mapping of species to edited source-grounded summaries")
    parser.add_argument("--coverage", action="store_true", help="Report the Pathogenwatch/QualiBact overlap without rendering")
    parser.add_argument("--all", action="store_true", help="Render the exact species-level overlap; report any failures")
    parser.add_argument("--preflight", action="store_true", help="Check source and layout limits without downloading plots")
    args = parser.parse_args()
    if not args.species and not args.coverage and not args.all:
        parser.error("provide a species, --coverage, or --all")
    overrides = json.loads(args.summaries.read_text()) if args.summaries else {}
    overlap = None
    if args.coverage or args.all:
        index = qualibact_species(args.refresh)
        mapped = ((PATHOGENWATCH_NAMES - EXCLUDE) & index) | (set(SPECIES_MAPPING.values()) & index)
        overlap, error_exclusions = eligible_species(mapped, args.refresh)
        exceptions = sorted((PATHOGENWATCH_NAMES - EXCLUDE - index) - set(SPECIES_MAPPING))
        report = {
            "pathogenwatch_source": SUPPORTED_SOURCE,
            "qualibact_source": "https://qualibact.org/species/",
            "pathogenwatch_entries": len(PATHOGENWATCH_NAMES),
            "qualibact_species": len(index),
            "dossier_species": overlap,
            "engine_error_exclusions": error_exclusions,
            "approved_exclusions": sorted(EXCLUDE),
            "explicit_species_mapping": SPECIES_MAPPING,
            "unresolved": exceptions,
        }
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Approved dossier species: {len(overlap)}; engine ERROR excluded: {len(error_exclusions)}; unresolved: {len(exceptions)}")
        if args.coverage and not args.all and not args.species:
            return
    targets = sorted(set(args.species) | (set(overlap or ()) if args.all else set()))
    failures = {}
    for species in targets:
        try:
            result = build(species, args.refresh, overrides, args.preflight)
            if result:
                print(*result, sep="\n")
            else:
                print(f"Preflight OK: {species}")
        except (ValueError, OSError, subprocess.CalledProcessError) as error:
            if not args.all:
                raise
            failures[species] = str(error)
    if args.all:
        report_name = "preflight-failures.json" if args.preflight else "batch-failures.json"
        (OUTPUT / report_name).write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
        verb = "Preflight passed" if args.preflight else "Rendered"
        print(f"{verb} {len(targets) - len(failures)}/{len(targets)}; failures in {report_name}")
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
