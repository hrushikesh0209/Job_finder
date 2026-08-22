import json
import tempfile
import unittest
from pathlib import Path

from extensions.job_alerts.config import ConfigError, import_saved_search, load_config


class ConfigTests(unittest.TestCase):
    def test_example_config_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "config.example.json"
        config = load_config(path)
        self.assertEqual(config["timezone"], "Asia/Kolkata")

    def test_invalid_interval_is_rejected(self):
        path = Path(__file__).resolve().parents[1] / "config.example.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["profiles"][0]["schedule"]["hours"] = 2
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid = Path(temp_dir) / "config.json"
            invalid.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(invalid)

    def test_import_copies_without_changing_source(self):
        extension = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "config.json"
            config_path.write_text(
                (extension / "config.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            saved_path = temp / "saved.json"
            saved_data = {
                "My Search": {
                    "titles": ["Data Analyst"],
                    "custom": "BI Analyst",
                    "country": "India",
                    "city": "Pune",
                    "sites": ["linkedin"],
                    "max_results": 25,
                    "hours_old": 24,
                    "remote_only": False,
                    "use_exp": True,
                    "exp_min": 1,
                    "exp_max": 3,
                }
            }
            original = json.dumps(saved_data, sort_keys=True)
            saved_path.write_text(json.dumps(saved_data), encoding="utf-8")

            profile_id = import_saved_search("My Search", config_path, saved_path)

            self.assertEqual(profile_id, "my-search")
            imported = load_config(config_path)["profiles"][-1]
            self.assertEqual(imported["titles"], ["Data Analyst", "BI Analyst"])
            self.assertFalse(imported["enabled"])
            self.assertEqual(
                json.dumps(json.loads(saved_path.read_text()), sort_keys=True), original
            )


if __name__ == "__main__":
    unittest.main()
