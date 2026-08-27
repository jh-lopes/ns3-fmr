import importlib.util
from pathlib import Path
import unittest

import pandas as pd


MODULO = Path(__file__).with_name("metodo_alfa_dinamico_vj5g.py")
spec = importlib.util.spec_from_file_location("metodo_alfa", MODULO)
metodo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metodo)


def linha(cenario, run_id, scheduler, window_id, time_s, jain, vazao):
    return {
        "scheduler": scheduler,
        "traffic_profile": "embb",
        "num_ues": 4,
        "seed": 1,
        "rng_run": 1,
        "bandwidth_mhz": 100.0,
        "window_id": window_id,
        "time_s": time_s,
        "aggregate_thr_mbps": vazao,
        "jain_throughput": jain,
        "cenario": cenario,
        "run_id": run_id,
    }


class MetodoAlfaTests(unittest.TestCase):
    def test_carrega_esquema_novo_e_padroniza_tempo(self):
        novo = pd.DataFrame([{
            "scheduler": "rr", "traffic_profile": "embb", "num_ues": 4,
            "seed": 1, "rng_run": 2, "bandwidth_mhz": 100,
            "window_id": 0, "start_time_s": 0.4, "end_time_s": 0.5,
            "duration_s": 0.1, "phase": "traffic",
            "metric_source": "app_rx_unique_payload",
            "aggregate_thr_mbps": 10.0, "jain_throughput": 0.9,
            "app_rx_packets": 100,
        }])
        carregado = metodo.carregar_window_log(novo, "A")
        self.assertEqual(carregado["time_s"].iloc[0], 0.5)
        self.assertEqual(carregado["run_id"].iloc[0], "1_2")
        self.assertEqual(carregado["window_schema"].iloc[0], "app_rx_unique_v2")
        self.assertEqual(carregado["metric_source"].iloc[0], "app_rx_unique_payload")

    def test_log_legado_e_bloqueado_por_padrao(self):
        legado = pd.DataFrame([linha("A", "1_1", "rr", 0, 0.5, 0.9, 10.0)]).drop(
            columns=["cenario", "run_id"]
        )
        with self.assertRaises(ValueError):
            metodo.carregar_window_log(legado, "A")
        with self.assertWarns(RuntimeWarning):
            carregado = metodo.carregar_window_log(
                legado, "A", permitir_log_legado=True
            )
        self.assertEqual(carregado["window_schema"].iloc[0], "rx_trace_legacy_v1")

    def test_rejeita_origem_de_metrica_inesperada(self):
        novo = pd.DataFrame([{
            "scheduler": "rr", "traffic_profile": "embb", "num_ues": 2,
            "seed": 1, "rng_run": 1, "bandwidth_mhz": 100,
            "window_id": 0, "start_time_s": 0.4, "end_time_s": 0.5,
            "duration_s": 0.1, "app_rx_packets": 10,
            "metric_source": "flowmon",
            "aggregate_thr_mbps": 1.0, "jain_throughput": 1.0,
        }])
        with self.assertRaises(ValueError):
            metodo.carregar_window_log(novo, "A")

    def test_pareto_e_isolamento_por_cenario(self):
        dados = pd.DataFrame([
            linha("A", "1_1", "rr", 0, 0.1, 0.9, 10.0),
            linha("A", "1_1", "pf", 0, 0.1, 0.8, 9.0),  # dominado
            linha("B", "1_1", "rr", 0, 0.1, 0.7, 20.0),
            linha("B", "1_1", "pf", 0, 0.1, 0.9, 15.0),
        ])
        vencedores = metodo._vencedores_por_janela(dados)
        self.assertEqual(len(vencedores), 2)
        self.assertEqual(vencedores.loc[vencedores["cenario"] == "A", "scheduler"].iloc[0], "rr")

    def test_reagregacao_usa_ordem_e_exige_opt_in_para_jain(self):
        dados = pd.DataFrame([
            linha("A", "1_1", "rr", i, (i + 1) / 10, 0.8 + i / 100, 10 + i)
            for i in range(5)
        ])
        with self.assertRaises(ValueError):
            metodo.reagregar_window_log(dados, 500)
        agregado = metodo.reagregar_window_log(
            dados, 500, permitir_media_jain_aproximada=True
        )
        self.assertEqual(len(agregado), 1)
        self.assertEqual(agregado["window_id"].iloc[0], 0)
        self.assertAlmostEqual(agregado["aggregate_thr_mbps"].iloc[0], 12.0)

    def test_persistencia_nunca_atravessa_runs(self):
        dados = pd.DataFrame([
            linha("A", "run_1", "rr", 0, 0.1, 0.9, 10),
            linha("A", "run_1", "rr", 1, 0.2, 0.7, 10),
            linha("A", "run_2", "rr", 0, 0.1, 0.7, 10),
            linha("A", "run_2", "rr", 1, 0.2, 0.9, 10),
        ])
        resultado = metodo.avaliar_violacoes(dados, 0.8)
        self.assertEqual(resultado["persistencia_por_run_pct"], {"run_1": 50.0, "run_2": 50.0})
        self.assertEqual(resultado["persistencia_max_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
