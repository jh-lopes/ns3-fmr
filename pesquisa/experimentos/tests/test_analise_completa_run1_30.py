import importlib.util
import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).parents[3] / "scripts-VJ5"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "analise_completa_Run1-30.py"
SPEC = importlib.util.spec_from_file_location("analise_completa_run1_30", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AnaliseCompletaRun130Tests(unittest.TestCase):
    def executions(self):
        rows = []
        for run in range(1, 31):
            for index, scheduler in enumerate(MODULE.SCHEDULERS):
                rows.append({
                    "scenario": "scenario", "scheduler": scheduler,
                    "rng_run": run, "status": "OK", "output_dir": "unused",
                    "throughput_mbps": 100 + index,
                    "jain": .90 + index * .01,
                    "window_throughput_mean_mbps": 100 + index,
                    "window_jain_mean": .90 + index * .01,
                    "position_hash": f"hash-{run}",
                })
        return pd.DataFrame(rows)

    def test_audit_requires_four_paired_schedulers(self):
        data = self.executions()
        report, errors = MODULE.audit(data, 1, 30)
        self.assertEqual(int(report["paired"].sum()), 30)
        self.assertEqual(errors, [])
        report, errors = MODULE.audit(data.drop(data.index[-1]), 1, 30)
        self.assertFalse(bool(report.loc[report.rng_run == 30, "paired"].iloc[0]))
        self.assertTrue(errors)

    def test_jmin_conservative_obeys_feasibility_and_loss(self):
        curve = pd.DataFrame({
            "jmin": [.90, .91, .92, .93],
            "feasibility": [1, 1, .95, .90],
            "throughput_mean": [100, 99, 95, 90],
            "throughput_loss": [0, .01, .05, .10],
        })
        selected = MODULE.select_jmin(curve)
        self.assertAlmostEqual(selected["jmin_conservative"], .92)

    def test_jmin_curve_selects_best_feasible_scheduler(self):
        data = self.executions()
        quality = data[["scenario", "rng_run", "scheduler"]].copy()
        quality["throughput_ue_p5_mbps"] = 1.0
        quality["zero_throughput_share"] = 0.0
        quality["pdr_mean_pct"] = 99.0
        quality["delay_p99_p95_ms"] = 10.0
        curve = MODULE.jmin_curve(data, quality, np.array([.90, .92, .94]))
        self.assertEqual(float(curve.loc[curve.jmin == .90, "throughput_mean"].iloc[0]), 103.0)
        self.assertEqual(float(curve.loc[curve.jmin == .94, "feasibility"].iloc[0]), 0.0)

    def test_discovers_runs_directly_from_scenario_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "static_random_50ues_500m"
            for scheduler in MODULE.SCHEDULERS:
                output = scenario / "run_001" / scheduler
                output.mkdir(parents=True)
                with (output / "ue_summary.csv").open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=(
                        "ue_id", "rng_run", "x_initial_m", "y_initial_m",
                        "z_initial_m", "throughput_agregado_mbps", "jain_vazao",
                    ))
                    writer.writeheader()
                    writer.writerow({"ue_id": 0, "rng_run": 1, "x_initial_m": 10,
                                     "y_initial_m": 20, "z_initial_m": 1.5,
                                     "throughput_agregado_mbps": 100,
                                     "jain_vazao": .9})
                with (output / "window_log.csv").open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=(
                        "aggregate_thr_mbps", "jain_throughput"))
                    writer.writeheader()
                    writer.writerow({"aggregate_thr_mbps": 99,
                                     "jain_throughput": .89})
            found = MODULE.discover_executions(scenario, 1, 1)
            self.assertEqual(len(found), 4)
            self.assertTrue(found["status"].eq("OK").all())
            self.assertTrue(found["position_hash"].nunique() == 1)


if __name__ == "__main__":
    unittest.main()
