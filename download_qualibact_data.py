#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11", "fonttools>=4", "qrcode[pil]>=8"]
# ///
"""Download the QualiBact inputs needed for offline dossier rendering.

The source HTML, manifests and three figure files per species live under
cache/qualibact/. A compact, auditable table/URL snapshot lives under data/.
Editorial summaries are *not* rewritten by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import build_qualibact_dossier as dossier


SNAPSHOT = dossier.ROOT / "data" / "qualibact-snapshot.json"


def cached_input(url: str, path: Path, refresh: bool) -> tuple[bytes, dict]:
    data = dossier.source_bytes(url, path, refresh)
    return data, {
        "url": url,
        "cache_path": str(path.relative_to(dossier.ROOT)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def raw_published_table(page: str, species: str) -> list[dict[str, str]]:
    heading = page.find("Suggested thresholds for")
    start = page.find("<table", heading)
    if heading < 0 or start < 0:
        raise ValueError(f"{species}: published threshold table not found")
    parser = dossier.PublishedTableParser()
    parser.feed(page[start:])
    if not parser.finished or not parser.rows:
        raise ValueError(f"{species}: published threshold table failed to parse")
    keys = ["metric", "fail_below", "warn_below", "warn_above", "fail_above"]
    rows = [dict(zip(keys, row)) for row in parser.rows[1:] if len(row) == 5]
    if len(rows) < len(dossier.METRICS):
        raise ValueError(f"{species}: incomplete published threshold table")
    return rows


def download_one(species: str, refresh: bool, page_already_refreshed: bool = False) -> dict:
    if species in dossier.EXCLUDE or (
        species not in dossier.PATHOGENWATCH_NAMES
        and species not in dossier.SPECIES_MAPPING.values()
    ):
        raise ValueError(f"{species}: outside the approved Pathogenwatch species scope")
    slug = species.replace(" ", "_")
    page_url = dossier.species_page_url(species)
    page_bytes, page_file = cached_input(
        page_url, dossier.CACHE / slug / "page.html", refresh and not page_already_refreshed
    )
    page = page_bytes.decode("utf-8", errors="replace")
    flag = dossier.engine_quality_flag(page)
    if flag == "ERROR":
        raise ValueError(f"{species}: engine quality flag ERROR; no dossier data pack")
    overview = dossier.OverviewParser()
    overview.feed(page)
    if not overview.description:
        raise ValueError(f"{species}: no QC overview on source page")
    scheme = dossier.scheme_from_page(overview.text)
    cache = dossier.CACHE / slug / scheme
    manifest_url = f"https://static.qualibact.org/static/species/{slug}/{scheme}/manifest.json"
    manifest_bytes, manifest_file = cached_input(
        manifest_url, cache / "manifest.json", refresh
    )
    manifest = json.loads(manifest_bytes)
    if manifest.get("scheme") != scheme or not manifest.get("thresholds"):
        raise ValueError(f"{species}: missing or mismatched preferred-scheme manifest")
    left, right, gc, has_n50 = dossier.plot_paths(species, slug, scheme, manifest)
    figures = {}
    for label, relative in (("left", left), ("right_top", right), ("right_bottom", gc)):
        url = f"https://static.qualibact.org/static/species/{urllib.parse.quote(relative, safe='/')}"
        _, figures[label] = cached_input(url, cache / "plots" / Path(relative).name, refresh)
    counts = manifest.get("counts", {})
    return {
        "qualibact_page": page_url,
        "preferred_scheme": scheme,
        "engine_flag": flag,
        "overview_source_text": " ".join(overview.description.split()),
        "genome_count": int(counts.get("genome_count", 0)) + int(counts.get("refseq_count", 0)),
        "refseq_count": int(counts.get("refseq_count", 0)),
        "published_thresholds_raw": raw_published_table(page, species),
        "published_thresholds_display": dossier.table_rows(species, page),
        "left_figure_is_filtered_n50_vs_contigs": has_n50,
        "source_files": {"page": page_file, "manifest": manifest_file, "figures": figures},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("species", nargs="*", help="Exact QualiBact binomial name")
    parser.add_argument("--all", action="store_true", help="Download all eligible Pathogenwatch species")
    parser.add_argument("--refresh", action="store_true", help="Replace cached inputs with live QualiBact files")
    args = parser.parse_args()
    if not args.all and not args.species:
        parser.error("provide --all or one or more species")

    exclusions = {}
    scope_names = set()
    names = set(args.species)
    if args.all:
        index = dossier.qualibact_species(args.refresh)
        mapped = ((dossier.PATHOGENWATCH_NAMES - dossier.EXCLUDE) & index) | (
            set(dossier.SPECIES_MAPPING.values()) & index
        )
        eligible, exclusions = dossier.eligible_species(mapped, args.refresh)
        scope_names = set(eligible)
        names.update(eligible)
    records = {}
    for species in sorted(names):
        records[species] = download_one(
            species, refresh=args.refresh,
            page_already_refreshed=args.all and species in scope_names,
        )
        print(f"Downloaded: {species}", flush=True)
    report = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "pathogenwatch_supported_organisms": dossier.SUPPORTED_SOURCE,
        "qualibact_species_index": "https://qualibact.org/species/",
        "engine_error_exclusions": exclusions,
        "species": records,
    }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} species to {SNAPSHOT}")


if __name__ == "__main__":
    main()
