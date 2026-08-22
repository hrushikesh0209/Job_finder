import unittest

from extensions.job_alerts.cv_secret import decode_cv_secret, encode_cv_text


class CvSecretTests(unittest.TestCase):
    def test_compressed_cv_round_trip(self):
        text = "Skills: Python, SQL, Docker\nExperience: 5 years"
        encoded = encode_cv_text(text)
        self.assertEqual(decode_cv_secret(encoded), text)
        self.assertNotIn("Python", encoded)

    def test_invalid_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_cv_secret("not-base64")


if __name__ == "__main__":
    unittest.main()
