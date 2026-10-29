import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "FANET_UAV"))

import airsim_trajectory_logger as logger


class AirSimTrajectoryLoggerTests(unittest.TestCase):
    def test_local_ned_translation_adds_signed_spawn_offsets(self):
        result = logger.to_common_ned((1.0, -2.0, 3.0), (5.0, 0.0, -2.0))
        self.assertEqual(result, (6.0, -2.0, 1.0))

    def test_shared_coordinates_reproduce_settings_geometry(self):
        settings_path = (
            ROOT
            / "local_validation"
            / "2026-10-29"
            / "airsim"
            / "airsim_settings.json"
        )
        origins = logger.load_vehicle_origins(
            settings_path, ["Drone1", "Drone2", "Drone3"]
        )
        self.assertAlmostEqual(math.dist(origins["Drone1"], origins["Drone2"]), 5.0)
        self.assertAlmostEqual(math.dist(origins["Drone1"], origins["Drone3"]), 5.0)
        self.assertAlmostEqual(
            math.dist(origins["Drone2"], origins["Drone3"]), math.sqrt(50.0)
        )

    def test_nonzero_orientation_is_rejected_without_verified_rotation(self):
        settings = {
            "SimMode": "Multirotor",
            "Vehicles": {
                "Drone1": {
                    "VehicleType": "SimpleFlight",
                    "X": 0,
                    "Y": 0,
                    "Z": -2,
                    "Yaw": 90,
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(settings), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nonzero Yaw"):
                logger.load_vehicle_origins(path, ["Drone1"])

    def test_nonfinite_common_coordinate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-finite"):
            logger.to_common_ned((float("nan"), 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_safe_mission_uses_negative_z_and_compact_waypoints(self):
        mission = logger.build_safe_square_mission()
        self.assertTrue(all(waypoint.z < 0 for waypoint in mission))
        self.assertTrue(all(waypoint.speed == 1.0 for waypoint in mission))
        self.assertLessEqual(max(abs(w.x) for w in mission), 2.0)
        self.assertLessEqual(max(abs(w.y) for w in mission), 2.0)


if __name__ == "__main__":
    unittest.main()
