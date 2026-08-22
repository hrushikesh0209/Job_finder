import unittest

import pandas as pd

from extensions.job_alerts.filters import (
    apply_experience_filter,
    extract_experience_range,
    qualifies_scores,
    rank_jobs,
)


class FilterTests(unittest.TestCase):
    def test_experience_patterns(self):
        self.assertEqual(extract_experience_range("Requires 2-5 years"), (2, 5))
        self.assertEqual(extract_experience_range("Minimum 4 years"), (4, 99))
        self.assertIsNone(extract_experience_range("Experience preferred"))

    def test_unspecified_experience_is_kept(self):
        frame = pd.DataFrame(
            [
                {"title": "Junior", "job_level": "", "description": "1-2 years"},
                {"title": "Senior", "job_level": "", "description": "8+ years"},
                {"title": "Unknown", "job_level": "", "description": ""},
            ]
        )
        result = apply_experience_filter(
            frame, {"enabled": True, "min_years": 0, "max_years": 3}
        )
        self.assertEqual(result["title"].tolist(), ["Junior", "Unknown"])

    def test_either_and_both_score_logic(self):
        job = {"match_score": 55, "ats_score": 40}
        rules = {
            "match": {"enabled": True, "minimum": 50},
            "ats": {"enabled": True, "minimum": 60},
            "score_logic": "either",
        }
        self.assertTrue(qualifies_scores(job, rules))
        rules["score_logic"] = "both"
        self.assertFalse(qualifies_scores(job, rules))

    def test_rank_without_score_columns(self):
        frame = pd.DataFrame([{"title": "A"}, {"title": "B"}])
        self.assertEqual(rank_jobs(frame)["title"].tolist(), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
