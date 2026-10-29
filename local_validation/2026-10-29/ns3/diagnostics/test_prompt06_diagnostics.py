import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_prompt06_diagnostics.py")
SPEC = importlib.util.spec_from_file_location("prompt06_diagnostics", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Prompt06DiagnosticsTests(unittest.TestCase):
    def test_linear_interpolation_quantile(self):
        self.assertEqual(MODULE.quantile([0.0, 10.0], 0.25), 2.5)

    def test_delay_thresholds_are_strictly_greater_than_cutoff(self):
        result = MODULE.stats([100.0, 100.1, 500.0, 1000.1])
        self.assertEqual(result["over_100ms"], 3)
        self.assertEqual(result["over_500ms"], 1)
        self.assertEqual(result["over_1000ms"], 1)

    def test_topology_shortest_hops_uses_evaluated_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mobility.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=["time_s", "node_id", "x_m", "y_m", "z_m"]
                )
                writer.writeheader()
                for node_id, x in (("a", 0), ("b", 30), ("c", 60), ("isolated", 130)):
                    writer.writerow(
                        {
                            "time_s": 0.0,
                            "node_id": node_id,
                            "x_m": x,
                            "y_m": 0,
                            "z_m": 0,
                        }
                    )
            points = MODULE.read_csv(path)
        self.assertEqual(MODULE.topology_min_hops(points, 0.0, "a", "c", 35.0), 2)
        self.assertIsNone(MODULE.topology_min_hops(points, 0.0, "a", "isolated", 35.0))

    def test_missing_evaluation_snapshot_is_not_fabricated(self):
        points = [{"time_s": "1.0", "node_id": "a", "x_m": "0", "y_m": "0", "z_m": "0"}]
        self.assertIsNone(MODULE.topology_min_hops(points, 0.0, "a", "b", 35.0))


if __name__ == "__main__":
    unittest.main()
