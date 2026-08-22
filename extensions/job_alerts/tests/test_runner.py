import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from extensions.job_alerts.email_sender import EmailSettings
from extensions.job_alerts.runner import run_profile


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "id": "test-profile",
            "label": "Test",
            "titles": ["Engineer"],
            "country": "India",
            "city": "Pune",
            "sites": ["linkedin"],
            "max_results": 10,
            "hours_old": 24,
            "remote_only": False,
            "experience": {"enabled": False},
            "schedule": {"kind": "interval", "hours": 3},
            "filters": {
                "match": {"enabled": False, "minimum": 0},
                "ats": {"enabled": False, "minimum": 0},
                "score_logic": "either",
                "max_email_jobs": 20,
            },
        }
        self.frame = pd.DataFrame(
            [
                {
                    "title": "Engineer",
                    "company": "Example",
                    "location": "Pune",
                    "job_url": "https://example.com/jobs/1",
                    "job_id": "1",
                    "site": "LinkedIn",
                    "date_posted": "2026-08-22",
                }
            ]
        )

    @patch("extensions.job_alerts.runner.send_message")
    @patch("extensions.job_alerts.runner.settings_from_env")
    @patch("extensions.job_alerts.runner._search")
    def test_successful_send_is_not_repeated(self, search, settings, send):
        search.return_value = self.frame
        settings.return_value = EmailSettings("from@gmail.com", "pw", "to@example.com")
        state = {"profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            first = run_profile(self.profile, state, state_path)
            second = run_profile(self.profile, state, state_path)
        self.assertEqual(first.status, "sent")
        self.assertEqual(second.status, "no-new-matches")
        self.assertEqual(send.call_count, 1)

    @patch("extensions.job_alerts.runner.send_message", side_effect=RuntimeError("SMTP down"))
    @patch("extensions.job_alerts.runner.settings_from_env")
    @patch("extensions.job_alerts.runner._search")
    def test_failed_send_does_not_mark_job(self, search, settings, send):
        search.return_value = self.frame
        settings.return_value = EmailSettings("from@gmail.com", "pw", "to@example.com")
        state = {"profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("extensions.job_alerts.runner.logger.exception"):
                result = run_profile(self.profile, state, Path(temp_dir) / "state.json")
        self.assertEqual(result.status, "error")
        self.assertEqual(state["profiles"]["test-profile"]["notified"], {})

    @patch("extensions.job_alerts.runner.send_message")
    @patch("extensions.job_alerts.runner.settings_from_env")
    @patch("extensions.job_alerts.runner._search")
    def test_dry_run_does_not_send_or_change_state(self, search, settings, send):
        search.return_value = self.frame
        state = {"profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_profile(
                self.profile, state, Path(temp_dir) / "state.json", dry_run=True
            )
        self.assertEqual(result.status, "dry-run")
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.emailed, 0)
        send.assert_not_called()
        self.assertNotIn("last_run_at", state["profiles"]["test-profile"])

    @patch("extensions.job_alerts.runner.send_message")
    @patch("extensions.job_alerts.runner.settings_from_env")
    @patch("extensions.job_alerts.runner._search")
    def test_each_profile_has_independent_delivery_history(self, search, settings, send):
        search.return_value = self.frame
        settings.return_value = EmailSettings("from@gmail.com", "pw", "to@example.com")
        second_profile = dict(self.profile, id="second-profile")
        state = {"profiles": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            first = run_profile(self.profile, state, state_path)
            second = run_profile(second_profile, state, state_path)
        self.assertEqual(first.status, "sent")
        self.assertEqual(second.status, "sent")
        self.assertEqual(send.call_count, 2)


if __name__ == "__main__":
    unittest.main()
