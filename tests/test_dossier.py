"""Source, scope and reproducibility checks for the two-page dossiers."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_qualibact_dossier as dossier  # noqa: E402
import make_qualibact_dossier_mockups as art  # noqa: E402
import download_qualibact_data as download  # noqa: E402


class DossierTests(unittest.TestCase):
    def test_engine_flags_and_missing_flag(self) -> None:
        self.assertEqual(dossier.engine_quality_flag("<h3>Engine quality flag: info</h3>"), "INFO")
        self.assertEqual(dossier.engine_quality_flag("<h3>Engine quality flag: warn</h3>"), "WARN")
        self.assertEqual(dossier.engine_quality_flag("<h3>Engine quality flag: error</h3>"), "ERROR")
        self.assertIsNone(dossier.engine_quality_flag("<h3>Preferred scheme</h3>"))
        with self.assertRaisesRegex(ValueError, "Unknown"):
            dossier.engine_quality_flag("<h3>Engine quality flag: critical</h3>")

    def test_error_blocks_direct_render_before_any_plot_download(self) -> None:
        page = b"<h1>Klebsiella africana QC Overview</h1><p>Test.</p><h3>Engine quality flag: error</h3>"
        with patch.object(dossier, "source_bytes", return_value=page) as fetch:
            with self.assertRaisesRegex(ValueError, "generation is prohibited"):
                dossier.build("Klebsiella africana", False, {}, preflight=False)
        self.assertEqual(fetch.call_count, 1)

    def test_flag_note_colours_and_omission(self) -> None:
        with patch.object(art, "SHOW_ENGINE_FLAG", False):
            self.assertEqual(art.flag_note(), "")
        with patch.object(art, "SHOW_ENGINE_FLAG", True), patch.object(art, "ENGINE_FLAG", "ERROR"):
            self.assertIn('#FCE7EB', art.flag_note())
        with patch.object(art, "SHOW_ENGINE_FLAG", True), patch.object(art, "ENGINE_FLAG", "INFO"):
            self.assertIn(art.LAVENDER, art.flag_note())

    def test_source_snapshot_is_complete_and_checksums_match(self) -> None:
        snapshot = json.loads(download.SNAPSHOT.read_text())
        summaries = json.loads((ROOT / "dossier_summaries.json").read_text())
        self.assertEqual(len(snapshot["species"]), 26)
        self.assertEqual(len(snapshot["engine_error_exclusions"]), 6)
        self.assertLessEqual(set(snapshot["species"]), set(summaries))
        for species, record in snapshot["species"].items():
            with self.subTest(species=species):
                self.assertNotEqual(record["engine_flag"], "ERROR")
                self.assertGreaterEqual(len(record["published_thresholds_raw"]), 7)
                files = record["source_files"]
                for item in (files["page"], files["manifest"], *files["figures"].values()):
                    path = ROOT / item["cache_path"]
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])

    def test_example_matches_offline_render(self) -> None:
        for species in ("Escherichia_coli", "Klebsiella_pneumoniae", "Campylobacter_coli"):
            for page in ("01-thresholds.png", "02-evidence.png"):
                with self.subTest(species=species, page=page):
                    expected = Image.open(ROOT / "examples" / species / page).convert("RGB")
                    actual = Image.open(dossier.OUTPUT / species / page).convert("RGB")
                    self.assertEqual(expected.size, (1080, 1350))
                    self.assertIsNone(ImageChops.difference(expected, actual).getbbox())


if __name__ == "__main__":
    unittest.main()
