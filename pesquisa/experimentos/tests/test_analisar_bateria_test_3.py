import importlib.util
import math
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[3] / "scripts-VJ5"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "analisar_bateria_test_3.py"
SPEC = importlib.util.spec_from_file_location("analisar_bateria_test_3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AnalisarBateriaTest3Tests(unittest.TestCase):
    def test_percentile_type_7(self):
        self.assertEqual(MODULE.percentile([0, 10, 20], 0.5), 10)
        self.assertAlmostEqual(MODULE.percentile([0, 10], 0.05), 0.5)

    def test_jain_includes_zero_throughput_ues(self):
        self.assertAlmostEqual(MODULE.jain([1.0, 1.0, 0.0, 0.0]), 0.5)

    def test_paired_tests_report_effect_wins_and_holm(self):
        rows = []
        for run in range(1, 5):
            for index, scheduler in enumerate(MODULE.SCHEDULERS):
                row = {
                    "scenario": "scenario", "rng_run": run,
                    "scheduler": scheduler,
                }
                for metric in MODULE.QUALITY_METRICS:
                    row[metric] = float(run + index)
                rows.append(row)
        tests = MODULE.paired_tests(rows)
        self.assertEqual(len(tests), 6 * len(MODULE.QUALITY_METRICS))
        self.assertTrue(all("p_value_holm" in row for row in tests))
        self.assertTrue(all(0 <= float(row["left_win_share"]) <= 1 for row in tests))
        self.assertFalse(any(math.isnan(float(row["mean_difference"])) for row in tests))


if __name__ == "__main__":
    unittest.main()
