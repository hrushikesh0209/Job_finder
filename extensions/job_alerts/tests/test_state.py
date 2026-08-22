import unittest
from datetime import datetime, timezone

from extensions.job_alerts.state import (
    due_profiles,
    is_profile_due,
    job_identity,
    mark_notified,
)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "id": "test",
            "enabled": True,
            "schedule": {"kind": "interval", "hours": 3},
        }

    def test_new_profile_is_due(self):
        self.assertTrue(is_profile_due(self.profile, {}, "Asia/Kolkata"))

    def test_interval_waits_until_elapsed(self):
        now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        state = {"last_run_at": "2026-08-22T10:00:00+00:00"}
        self.assertFalse(is_profile_due(self.profile, state, "Asia/Kolkata", now))
        state["last_run_at"] = "2026-08-22T08:59:00+00:00"
        self.assertTrue(is_profile_due(self.profile, state, "Asia/Kolkata", now))

    def test_daily_uses_configured_timezone(self):
        profile = {
            "id": "daily",
            "enabled": True,
            "schedule": {"kind": "daily", "time": "08:30"},
        }
        now = datetime(2026, 8, 22, 3, 30, tzinfo=timezone.utc)  # 09:00 IST
        state = {"last_run_at": "2026-08-21T04:00:00+00:00"}
        self.assertTrue(is_profile_due(profile, state, "Asia/Kolkata", now))

    def test_disabled_profile_is_not_due(self):
        self.profile["enabled"] = False
        config = {"timezone": "Asia/Kolkata", "profiles": [self.profile]}
        self.assertEqual(due_profiles(config, {"profiles": {}}), [])

    def test_identity_normalizes_tracking_parameters(self):
        first = job_identity({"job_url": "https://Example.com/job/1?utm_source=x&a=1"})
        second = job_identity({"job_url": "https://example.com/job/1?a=1"})
        self.assertEqual(first, second)

    def test_mark_notified_records_only_hashes(self):
        state = {}
        mark_notified(state, ["abc"])
        self.assertEqual(set(state["notified"]), {"abc"})


if __name__ == "__main__":
    unittest.main()
