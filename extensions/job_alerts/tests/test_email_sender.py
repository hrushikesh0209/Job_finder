import unittest
from unittest.mock import patch

from extensions.job_alerts.email_sender import (
    EmailSettings,
    build_digest_message,
    send_message,
    validated_job_url,
)


class EmailTests(unittest.TestCase):
    def setUp(self):
        self.settings = EmailSettings("sender@gmail.com", "secret", "to@example.com")

    def test_digest_escapes_scraped_content_and_rejects_unsafe_url(self):
        message = build_digest_message(
            {"id": "test", "label": "<Alert>"},
            [
                {
                    "title": "<script>alert(1)</script>",
                    "company": "A&B",
                    "job_url": "javascript:alert(1)",
                    "match_score": 70,
                    "ats_score": 80,
                }
            ],
            self.settings,
        )
        body = message.get_body(preferencelist=("html",)).get_content()
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("javascript:", body)

    def test_url_validation(self):
        self.assertEqual(validated_job_url("https://example.com/job"), "https://example.com/job")
        self.assertEqual(validated_job_url("file:///secret"), "")

    @patch("extensions.job_alerts.email_sender.smtplib.SMTP")
    def test_smtp_uses_starttls_and_login(self, smtp_class):
        smtp = smtp_class.return_value.__enter__.return_value
        message = build_digest_message({"id": "test"}, [], self.settings)
        send_message(message, self.settings)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("sender@gmail.com", "secret")
        smtp.send_message.assert_called_once_with(message)


if __name__ == "__main__":
    unittest.main()
