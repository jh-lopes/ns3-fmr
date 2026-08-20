import csv
import importlib.util
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT = Path(__file__).parents[3] / "scripts-VJ5" / "bateria_test_3.py"
SPEC = importlib.util.spec_from_file_location("bateria_test_3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BateriaTest3Tests(unittest.TestCase):
    def write_positions(self, path: Path, rng_run: int, offset: float = 0.0):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("ue_id", "rng_run", "x_initial_m",
                            "y_initial_m", "z_initial_m"),
            )
            writer.writeheader()
            writer.writerows([
                {"ue_id": 0, "rng_run": rng_run, "x_initial_m": 10 + offset,
                 "y_initial_m": 1, "z_initial_m": 1.5},
                {"ue_id": 1, "rng_run": rng_run, "x_initial_m": 20 + offset,
                 "y_initial_m": 2, "z_initial_m": 1.5},
            ])

    def test_position_hash_is_stable_and_changes_with_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            same = Path(directory) / "same.csv"
            other = Path(directory) / "other.csv"
            self.write_positions(first, 1)
            self.write_positions(same, 1)
            self.write_positions(other, 2, offset=3)
            self.assertEqual(MODULE.position_hash(first, 1),
                             MODULE.position_hash(same, 1))
            self.assertNotEqual(MODULE.position_hash(first, 1),
                                MODULE.position_hash(other, 2))

    def test_position_hash_rejects_wrong_rng_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "positions.csv"
            self.write_positions(path, 1)
            with self.assertRaisesRegex(RuntimeError, "rng_run"):
                MODULE.position_hash(path, 2)

    def test_pairing_rejects_different_scheduler_topologies(self):
        scenario = MODULE.Scenario(10, 100)
        rows = [
            {"scenario": scenario.name, "rng_run": "1", "scheduler": scheduler,
             "status": "OK", "position_hash": "same"}
            for scheduler in MODULE.SCHEDULERS
        ]
        MODULE.validate_pairing(rows, scenario, 1)
        rows[-1]["position_hash"] = "different"
        with self.assertRaisesRegex(RuntimeError, "não pareada"):
            MODULE.validate_pairing(rows, scenario, 1)

    def test_battery_has_one_configurable_scenario(self):
        self.assertEqual(MODULE.scenarios(50, 500), [MODULE.Scenario(50, 500)])

    def test_distinct_runs_reject_reused_topology(self):
        scenario = MODULE.Scenario(50, 500)
        rows = [
            {"scenario": scenario.name, "rng_run": str(run), "scheduler": "rr",
             "status": "OK", "position_hash": position_hash}
            for run, position_hash in ((1, "a"), (2, "b"))
        ]
        MODULE.validate_distinct_runs(rows, scenario)
        rows[-1]["position_hash"] = "a"
        with self.assertRaisesRegex(RuntimeError, "reutilizaram"):
            MODULE.validate_distinct_runs(rows, scenario)

    def test_convergence_requires_every_scheduler(self):
        scenario = MODULE.Scenario(10, 100)
        args = Namespace(min_runs=2, throughput_error=0.05, jain_error=0.01)
        rows = []
        for scheduler in MODULE.SCHEDULERS:
            for run in (1, 2):
                rows.append({
                    "scenario": scenario.name, "scheduler": scheduler,
                    "status": "OK", "window_throughput_mean_mbps": "100",
                    "window_jain_mean": "0.9", "rng_run": str(run),
                })
        self.assertTrue(MODULE.converged(rows, scenario, args))
        rows.pop()
        self.assertFalse(MODULE.converged(rows, scenario, args))


if __name__ == "__main__":
    unittest.main()
