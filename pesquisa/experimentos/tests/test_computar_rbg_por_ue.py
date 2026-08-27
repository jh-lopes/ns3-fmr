import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[3] / "scripts-VJ5" / "computar_rbg_por_ue.py"
SPEC = importlib.util.spec_from_file_location("computar_rbg_por_ue", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ResourceUnitTests(unittest.TestCase):
    def test_legacy_column_is_explicitly_normalized(self):
        frame = pd.DataFrame({"alloc_rbg": [12]})
        normalized = MODULE.normalizar_coluna_recurso(frame)
        self.assertIn("allocated_rbg_symbol_units", normalized.columns)
        self.assertNotIn("alloc_rbg", normalized.columns)

    def test_aggregated_resource_counts_are_exported_as_integers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ue_path = root / "ue.csv"
            slot_path = root / "slot.csv"
            output = root / "result.csv"
            pd.DataFrame({
                "ue_id": [0], "rnti": [7], "rb_per_rbg": [2],
            }).to_csv(ue_path, index=False)
            pd.DataFrame({
                "time_s": [0.1, 0.2], "rnti": [7, 7],
                "allocated_rbg_symbol_units": [10, 11],
            }).to_csv(slot_path, index=False)

            MODULE.computar(ue_path, slot_path, output)
            result = pd.read_csv(output)
            self.assertEqual(int(result.loc[0, "rbg_symbol_units_total"]), 21)
            self.assertEqual(int(result.loc[0, "rb_symbol_units_total"]), 42)
            header, row = output.read_text(encoding="utf-8").splitlines()[:2]
            values = dict(zip(header.split(","), row.split(",")))
            self.assertEqual(values["rbg_symbol_units_total"], "21")
            self.assertEqual(values["rb_symbol_units_total"], "42")
            self.assertEqual(values["scheduled_events"], "2")


if __name__ == "__main__":
    unittest.main()
