"""Small checks for the verifier, unknown accounting, routing, and spending cap."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from agent import Budget, complete_sum, luna_usage, select_route
from verify import verify

SOURCE = Path(__file__).parent / "data/DKNYgirl.png"


class Checks(unittest.TestCase):
    def test_verifier_accepts_correct_and_rejects_corrupt_or_wrong_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "output.png"
            self.assertFalse(verify(SOURCE, output, "technical")["technical_success"])
            with Image.open(SOURCE) as image:
                image.resize((512, 337), Image.Resampling.LANCZOS).save(output)
            self.assertTrue(verify(SOURCE, output, "technical")["technical_success"])
            self.assertFalse(verify(SOURCE, output, "visual")["technical_success"])
            Image.new("RGB", (512, 337)).save(output)
            self.assertFalse(verify(SOURCE, output, "technical")["technical_success"])
            output.write_bytes(b"not an image")
            self.assertFalse(verify(SOURCE, output, "technical")["technical_success"])

    def test_visual_dimensions_do_not_imply_visual_success(self):
        result = verify(SOURCE, SOURCE.parent / "DKNYgirl_0.50_cr.png", "visual")
        self.assertTrue(result["technical_success"])
        self.assertEqual(result["visual_status"], "pending")

    def test_budget_persists_unknown_reservations_and_blocks_before_spending(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "budget.json"
            budget = Budget(path)
            first = budget.reserve("openai")
            budget.settle(first, None)
            for _ in range(9):
                Budget(path).reserve("openai")
            with self.assertRaises(RuntimeError):
                budget.reserve("typesafe")
            budget.settle(first, 0.01)
            budget.reserve("typesafe")
            self.assertEqual(len(json.loads(path.read_text())["calls"]), 11)

    def test_unknown_usage_is_never_zero(self):
        self.assertIsNone(luna_usage(None)["cost_usd"])
        self.assertIsNone(complete_sum([1, None]))
        usage = luna_usage({"input_tokens": 1000, "output_tokens": 100, "input_tokens_details": {"cached_tokens": 200}})
        self.assertAlmostEqual(usage["cost_lower_usd"], 0.000284)
        self.assertGreater(usage["cost_usd"], usage["cost_lower_usd"])

    def test_route_requires_confidence_and_unambiguous_parameters(self):
        class Classifier:
            async def ainvoke(self, request):
                answer = SimpleNamespace(choice="proportional_width", confidence=0.99,
                                         model_dump=lambda: {"choice": "proportional_width", "confidence": 0.99})
                return SimpleNamespace(choices={"route": answer}, model_dump=lambda: {"model": "test-double"})
        good = asyncio.run(select_route("Resize to width 512 preserving aspect ratio", Classifier()))
        self.assertEqual(good["route"], "proportional_width")
        for request in ["Resize it", "width 0", "width 99999", "width 512 or width 300"]:
            self.assertEqual(asyncio.run(select_route(request, Classifier()))["route"], "luna")


if __name__ == "__main__":
    unittest.main()
