import json
import tempfile
import unittest
from pathlib import Path

from audit.golden import ROOT, compare, crop_box, frozen_references, pixels


class GoldenChecks(unittest.TestCase):
    def test_exact_identity_shift_and_shape_are_distinguished(self):
        source = pixels(ROOT / "data/DKNYgirl.png")
        gold = pixels(ROOT / "data/DKNYgirl_0.50_cr.png")
        self.assertTrue(compare(gold, gold)["exact_pixels"])
        self.assertEqual(crop_box(source, gold), [136, 0, 648, 673])
        shifted = source.crop((128, 0, 640, 673))
        self.assertFalse(compare(shifted, gold)["exact_pixels"])
        self.assertGreater(compare(shifted, gold)["mae_0_255"], 0)
        self.assertEqual(crop_box(source, shifted), [128, 0, 640, 673])
        self.assertFalse(compare(source, gold)["same_dimensions"])
        transparent = gold.copy()
        transparent.putalpha(0)
        self.assertFalse(compare(transparent, gold)["exact_pixels"])
        self.assertEqual(compare(transparent, gold)["matching_pixel_fraction"], 0)

    def test_reference_integrity_and_missing_data_fail_closed(self):
        manifest = json.loads((ROOT / "dataset.lock.json").read_text())
        self.assertEqual(len(frozen_references(ROOT / "data", manifest)), 8)
        manifest["files"][0]["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            frozen_references(ROOT / "data", manifest)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                frozen_references(Path(folder), manifest)
