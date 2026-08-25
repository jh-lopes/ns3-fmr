import csv
import importlib.util
import math
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts-VJ5" / "bateria_test_4.py"
SPEC = importlib.util.spec_from_file_location("bateria_test_4", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BateriaTest4Tests(unittest.TestCase):
    def write_fixture(self, root: Path, *, flow_delta=0, duplicate=0,
                      radius=100.0, broken_window=False,
                      application_mode="udp", radio_samples=True,
                      rsrq_available=True):
        ue = root / "ue_summary.csv"
        window = root / "window_log.csv"
        ue_fields = (
            "rng_run", "application_mode", "flows_per_ue", "ue_id", "x_initial_m", "y_initial_m", "z_initial_m",
            "distance_gnb_m", "app_throughput_traffic_mbps",
            "app_goodput_total_mbps", "app_jain_traffic", "app_jain_total",
            "flowmon_throughput_mbps", "flowmon_jain", "app_rx_packets_total",
            "flowmon_rx_packets", "app_duplicate_packets",
            "app_malformed_packets",
            "cqi_mean", "cqi_samples", "mcs_recommended_mean", "rank_mean",
            "rsrp_mean_dbm", "rsrq_mean_db", "rsrq_available",
            "measurement_samples",
            "rb_per_rbg", "channel_scenario", "channel_condition",
            "channel_model", "shadowing_enabled",
            "app_throughput_traffic_aggregate_mbps",
            "app_goodput_total_aggregate_mbps",
            "flowmon_throughput_aggregate_mbps",
        )
        with ue.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ue_fields)
            writer.writeheader()
            for ue_id, x in enumerate((20.0, radius)):
                writer.writerow({
                    "rng_run": 1, "application_mode": application_mode,
                    "flows_per_ue": 2,
                    "ue_id": ue_id, "x_initial_m": x,
                    "y_initial_m": 0, "z_initial_m": 1.5,
                    "distance_gnb_m": math.sqrt(x*x + 23.5**2),
                    "app_throughput_traffic_mbps": 1.0,
                    "app_goodput_total_mbps": 1.2,
                    "app_jain_traffic": 1.0, "app_jain_total": 1.0,
                    "flowmon_throughput_mbps": 1.23, "flowmon_jain": 1.0,
                    "app_rx_packets_total": 100,
                    "flowmon_rx_packets": 100 + flow_delta,
                    "app_duplicate_packets": duplicate,
                    "app_malformed_packets": 0,
                    "cqi_mean": 10 if radio_samples else "nan",
                    "cqi_samples": 20 if radio_samples else 0,
                    "mcs_recommended_mean": 12 if radio_samples else "nan",
                    "rank_mean": 1 if radio_samples else "nan",
                    "rsrp_mean_dbm": -85 if radio_samples else "nan",
                    "rsrq_mean_db": (-10 if radio_samples and rsrq_available
                                     else ""),
                    "rsrq_available": ("true" if radio_samples and rsrq_available
                                       else "false"),
                    "measurement_samples": 15 if radio_samples else 0,
                    "rb_per_rbg": 1, "channel_scenario": "UMa",
                    "channel_condition": "Default",
                    "channel_model": "ThreeGpp", "shadowing_enabled": "true",
                    "app_throughput_traffic_aggregate_mbps": 2.0,
                    "app_goodput_total_aggregate_mbps": 2.4,
                    "flowmon_throughput_aggregate_mbps": 2.46,
                })
        window_fields = (
            "rng_run", "flows_per_ue", "window_id", "start_time_s", "end_time_s",
            "duration_s", "phase", "aggregate_thr_mbps",
            "jain_throughput", "app_rx_packets",
        )
        with window.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=window_fields)
            writer.writeheader()
            writer.writerow({"rng_run": 1, "flows_per_ue": 2, "window_id": 0,
                             "start_time_s": .4, "end_time_s": .5,
                             "duration_s": .1, "phase": "traffic",
                             "aggregate_thr_mbps": 2, "jain_throughput": 1,
                             "app_rx_packets": 10})
            writer.writerow({"rng_run": 1,
                             "flows_per_ue": 2,
                             "window_id": 3 if broken_window else 1,
                             "start_time_s": .5, "end_time_s": .6,
                             "duration_s": .1, "phase": "drain",
                             "aggregate_thr_mbps": 1, "jain_throughput": 1,
                             "app_rx_packets": 5})
        return ue, window

    def test_corrected_outputs_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory))
            metrics = MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)
            self.assertEqual(metrics["app_flowmon_packet_delta"], 0)
            self.assertEqual(metrics["app_throughput_traffic_mbps"], 2.0)
            self.assertEqual(metrics["ues_with_cqi"], 2)
            self.assertEqual(metrics["ues_with_measurements"], 2)
            self.assertEqual(metrics["ues_with_rsrq"], 2)

    def test_flowmonitor_application_divergence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory), flow_delta=-1)
            with self.assertRaisesRegex(RuntimeError, "UdpServer/FlowMonitor"):
                MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)

    def test_http_does_not_compare_rx_events_with_ip_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(
                Path(directory), flow_delta=-10, application_mode="http")
            metrics = MODULE.validate_corrected_outputs(
                ue, window, 1, 2, 100, 2, "http")
            self.assertEqual(metrics["app_flowmon_packet_delta"], 20)

    def test_missing_radio_traces_are_counted_not_replaced_by_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory), radio_samples=False)
            metrics = MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)
            self.assertEqual(metrics["ues_with_cqi"], 0)
            self.assertEqual(metrics["ues_with_measurements"], 0)
            self.assertEqual(metrics["ues_with_rsrq"], 0)
            self.assertTrue(math.isnan(metrics["cqi_mean"]))
            self.assertTrue(math.isnan(metrics["rsrp_mean_dbm"]))

    def test_channel_configuration_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "canal divergente"):
                MODULE.validate_corrected_outputs(
                    ue, window, 1, 2, 100, 2, channel_scenario="UMi")

    def test_zero_rsrq_is_marked_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory), rsrq_available=False)
            metrics = MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)
            self.assertEqual(metrics["ues_with_measurements"], 2)
            self.assertEqual(metrics["ues_with_rsrq"], 0)
            self.assertTrue(math.isnan(metrics["rsrq_mean_db"]))

    def test_duplicate_application_packets_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory), duplicate=1)
            with self.assertRaisesRegex(RuntimeError, "duplicatas"):
                MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)

    def test_position_outside_annulus_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory), radius=101)
            with self.assertRaisesRegex(RuntimeError, "anel espacial"):
                MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)

    def test_window_gaps_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory), broken_window=True)
            with self.assertRaisesRegex(RuntimeError, "lacunas"):
                MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 2)

    def test_offered_load_multiplies_flows_per_ue(self):
        scenario = MODULE.Scenario(10, 100, "udp")
        self.assertEqual(MODULE.udp_offered_load_mbps(scenario, 500, 3), 180.0)

    def test_flow_count_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ue, window = self.write_fixture(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "flows_per_ue"):
                MODULE.validate_corrected_outputs(ue, window, 1, 2, 100, 3)

    def test_smoke_sets_short_traffic_and_drain(self):
        args = Namespace(smoke=True, sim_time=30.0, drain_time=15.0,
                         min_runs=30, max_runs=100, batch_size=10)
        MODULE.apply_smoke_defaults(args)
        self.assertEqual((args.sim_time, args.drain_time), (1.0, 1.0))
        self.assertEqual((args.min_runs, args.max_runs, args.batch_size), (1, 1, 1))

    def test_ledger_contains_provenance_and_reconciliation(self):
        expected = {
            "flows_per_ue",
            "traffic_stop_s", "drain_time_s", "flow_max_per_hop_delay_s",
            "metadata_sha256", "app_rx_packets_total",
            "flowmon_rx_packets_total", "app_flowmon_packet_delta",
        }
        self.assertTrue(expected.issubset(MODULE.FIELDS))

    def test_scenarios_cover_udp_http_and_mixed(self):
        scenarios = MODULE.scenarios(50, 500, ("udp", "http", "mixed"))
        self.assertEqual([item.application_mode for item in scenarios],
                         ["udp", "http", "mixed"])
        self.assertEqual(len({item.name for item in scenarios}), 3)

    def test_channel_configuration_changes_scenario_identity(self):
        uma = MODULE.scenarios(50, 500, ("udp",), "UMa")[0]
        umi = MODULE.scenarios(50, 500, ("udp",), "UMi")[0]
        no_shadowing = MODULE.scenarios(
            50, 500, ("udp",), "UMa", shadowing_enabled=False)[0]
        self.assertEqual(len({uma.name, umi.name, no_shadowing.name}), 3)


if __name__ == "__main__":
    unittest.main()
