from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "analise_vj5g.py"
SPEC = importlib.util.spec_from_file_location("analise_vj5g", MODULE_PATH)
assert SPEC and SPEC.loader
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def sample(rows):
    return pd.DataFrame(
        [
            {
                "scheduler": scheduler,
                "window_id": window,
                "aggregate_thr_mbps": throughput,
                "jain_throughput": fairness,
            }
            for scheduler, window, throughput, fairness in rows
        ]
    )


class ParetoTests(unittest.TestCase):
    def test_marks_dominated_and_tradeoff_points(self):
        data = sample([
            ("rr", 0, 40.0, 0.95),
            ("pf", 0, 55.0, 0.85),
            ("mr", 0, 65.0, 0.40),
            ("x", 0, 30.0, 0.70),
        ])
        result = analysis.mark_pareto_front(data, ["window_id"])
        flags = result.set_index("scheduler")["pareto_nao_dominado"].to_dict()
        self.assertEqual(flags, {"rr": True, "pf": True, "mr": True, "x": False})

    def test_equal_fairness_higher_throughput_dominates(self):
        data = sample([("rr", 0, 40.0, 0.9), ("pf", 0, 50.0, 0.9)])
        result = analysis.mark_pareto_front(data, ["window_id"])
        self.assertEqual(result["pareto_nao_dominado"].tolist(), [False, True])

    def test_duplicate_points_remain_on_front(self):
        data = sample([("rr", 0, 50.0, 0.9), ("pf", 0, 50.0, 0.9)])
        result = analysis.mark_pareto_front(data, ["window_id"])
        self.assertEqual(result["pareto_nao_dominado"].tolist(), [True, True])


class ValidationTests(unittest.TestCase):
    def test_rejects_missing_column(self):
        with self.assertRaisesRegex(analysis.AnalysisError, "jain_throughput"):
            analysis.validate_window_data(pd.DataFrame({"scheduler": ["rr"], "window_id": [0], "aggregate_thr_mbps": [1]}))

    def test_rejects_invalid_fairness(self):
        with self.assertRaisesRegex(analysis.AnalysisError, "intervalo"):
            analysis.validate_window_data(sample([("rr", 0, 1.0, 1.2)]))

    def test_rejects_non_finite_values(self):
        with self.assertRaisesRegex(analysis.AnalysisError, "não finito"):
            analysis.validate_window_data(sample([("rr", 0, float("inf"), 0.8)]))

    def test_rejects_missing_requested_group_column(self):
        data = sample([("rr", 0, 1.0, 0.9), ("pf", 0, 2.0, 0.8)])
        with self.assertRaisesRegex(analysis.AnalysisError, "seed"):
            analysis.mark_pareto_front(data, ["seed", "window_id"])

    def test_rejects_single_scheduler(self):
        with self.assertRaisesRegex(analysis.AnalysisError, "ao menos dois"):
            analysis.mark_pareto_front(sample([("rr", 0, 1.0, 0.9)]), ["window_id"])

    def test_rejects_duplicate_scheduler_in_window(self):
        data = sample([
            ("rr", 0, 1.0, 0.9),
            ("rr", 0, 1.0, 0.9),
            ("pf", 0, 2.0, 0.8),
        ])
        with self.assertRaisesRegex(analysis.AnalysisError, "duplicadas"):
            analysis.mark_pareto_front(data, ["window_id"])

    def test_rejects_incomplete_window(self):
        data = sample([
            ("rr", 0, 1.0, 0.9),
            ("pf", 0, 2.0, 0.8),
            ("rr", 1, 1.5, 0.9),
        ])
        with self.assertRaisesRegex(analysis.AnalysisError, "incompletas"):
            analysis.mark_pareto_front(data, ["window_id"])

    def test_rejects_time_misalignment(self):
        data = sample([("rr", 0, 1.0, 0.9), ("pf", 0, 2.0, 0.8)])
        data["time_s"] = [0.1, 0.2]
        with self.assertRaisesRegex(analysis.AnalysisError, "desalinhados"):
            analysis.mark_pareto_front(data, ["window_id"])

    def test_rejects_invalid_numeric_options(self):
        for epsilon in (-1.0, float("nan"), float("inf")):
            with self.subTest(epsilon=epsilon):
                with self.assertRaisesRegex(analysis.AnalysisError, "epsilon"):
                    analysis.validate_analysis_options(epsilon)
        with self.assertRaisesRegex(analysis.AnalysisError, "finita"):
            analysis.validate_analysis_options(1e-9, float("inf"))


class NashAndRankingTests(unittest.TestCase):
    def test_selects_best_nash_product(self):
        marked = analysis.mark_pareto_front(
            sample([("rr", 0, 40.0, 1.0), ("pf", 0, 80.0, 0.7), ("mr", 0, 100.0, 0.4)]),
            ["window_id"],
        )
        scored, _ = analysis.add_nash_scores(marked, throughput_reference=100.0)
        winners = analysis.select_nash_winners(scored, ["window_id"])
        self.assertEqual(winners["scheduler"].tolist(), ["pf"])

    def test_records_ties_and_splits_nash_credit(self):
        marked = analysis.mark_pareto_front(
            sample([("rr", 0, 50.0, 0.8), ("pf", 0, 50.0, 0.8)]),
            ["window_id"],
        )
        scored, _ = analysis.add_nash_scores(marked, throughput_reference=100.0)
        winners = analysis.select_nash_winners(scored, ["window_id"])
        ranking = analysis.rank_schedulers(scored, winners, ["window_id"])
        self.assertTrue(winners["nash_empate"].all())
        self.assertEqual(ranking["vitorias_nash_equivalentes"].tolist(), [0.5, 0.5])

    def test_rejects_reference_below_observed_maximum(self):
        marked = analysis.mark_pareto_front(
            sample([("rr", 0, 50.0, 0.9), ("pf", 0, 100.0, 0.7)]),
            ["window_id"],
        )
        with self.assertRaisesRegex(analysis.AnalysisError, "máximo observado"):
            analysis.add_nash_scores(marked, throughput_reference=80.0)

    def test_pipeline_writes_all_outputs(self):
        data = sample([("rr", 0, 40.0, 1.0), ("pf", 0, 50.0, 0.8)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.csv"
            data.to_csv(input_path, index=False)
            paths = analysis.run_analysis(input_path, root / "out", group_columns=["window_id"])
            self.assertTrue(all(path.exists() for path in paths.values()))
            self.assertEqual(len(pd.read_csv(paths["ranking"])), 2)


if __name__ == "__main__":
    unittest.main()
