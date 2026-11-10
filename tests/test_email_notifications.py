import os
import smtplib
import unittest
from unittest.mock import patch

from flask import Flask

from services.email_notifications import send_notification_email


class EmailNotificationServiceTests(unittest.TestCase):
    def test_disabled_delivery_does_not_connect_to_smtp(self):
        with (
            patch.dict(
                os.environ,
                {"SKILLSWAP_EMAIL_ENABLED": "false"},
            ),
            patch("services.email_notifications.smtplib.SMTP") as smtp,
        ):
            self.assertFalse(
                send_notification_email(
                    "member@example.test",
                    "Subject",
                    "Body",
                )
            )
        smtp.assert_not_called()

    def test_delivery_returns_true_only_after_smtp_accepts_message(self):
        environment = {
            "SKILLSWAP_EMAIL_ENABLED": "true",
            "SKILLSWAP_SMTP_HOST": "smtp.example.test",
            "SKILLSWAP_SMTP_PORT": "587",
            "SKILLSWAP_EMAIL_FROM": "noreply@example.test",
            "SKILLSWAP_SMTP_USERNAME": "",
            "SKILLSWAP_SMTP_PASSWORD": "",
        }
        with (
            patch.dict(os.environ, environment),
            patch("services.email_notifications.smtplib.SMTP") as smtp_class,
        ):
            smtp = smtp_class.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            sent = send_notification_email(
                "member@example.test",
                "Subject",
                "Body",
            )

        self.assertTrue(sent)
        smtp.starttls.assert_called_once()
        smtp.send_message.assert_called_once()
        email = smtp.send_message.call_args.args[0]
        self.assertEqual(email["To"], "member@example.test")
        smtp.login.assert_not_called()

    def test_automated_testing_suppresses_smtp_delivery(self):
        application = Flask(__name__)
        application.testing = True
        environment = {
            "SKILLSWAP_EMAIL_ENABLED": "true",
            "SKILLSWAP_SMTP_HOST": "smtp.example.test",
            "SKILLSWAP_EMAIL_FROM": "noreply@example.test",
            "SKILLSWAP_SMTP_USERNAME": "",
            "SKILLSWAP_SMTP_PASSWORD": "",
        }
        with (
            application.app_context(),
            patch.dict(os.environ, environment),
            patch("services.email_notifications.smtplib.SMTP") as smtp,
        ):
            self.assertFalse(
                send_notification_email(
                    "member@example.test",
                    "Subject",
                    "Body",
                )
            )
        smtp.assert_not_called()

    def test_partial_smtp_authentication_configuration_is_rejected(self):
        environment = {
            "SKILLSWAP_EMAIL_ENABLED": "true",
            "SKILLSWAP_SMTP_HOST": "smtp.example.test",
            "SKILLSWAP_EMAIL_FROM": "noreply@example.test",
            "SKILLSWAP_SMTP_USERNAME": "mail-user",
            "SKILLSWAP_SMTP_PASSWORD": "",
        }
        with (
            patch.dict(os.environ, environment),
            patch("services.email_notifications.smtplib.SMTP") as smtp_class,
        ):
            smtp = smtp_class.return_value.__enter__.return_value
            with self.assertRaisesRegex(RuntimeError, "Both"):
                send_notification_email(
                    "member@example.test",
                    "Subject",
                    "Body",
                )
        smtp_class.assert_not_called()

    def test_refused_recipient_is_reported_as_failed_delivery(self):
        environment = {
            "SKILLSWAP_EMAIL_ENABLED": "true",
            "SKILLSWAP_SMTP_HOST": "smtp.example.test",
            "SKILLSWAP_EMAIL_FROM": "noreply@example.test",
            "SKILLSWAP_SMTP_USERNAME": "",
            "SKILLSWAP_SMTP_PASSWORD": "",
        }
        with (
            patch.dict(os.environ, environment),
            patch("services.email_notifications.smtplib.SMTP") as smtp_class,
        ):
            smtp = smtp_class.return_value.__enter__.return_value
            smtp.send_message.return_value = {"member@example.test": (550, b"Rejected")}
            with self.assertRaises(smtplib.SMTPRecipientsRefused):
                send_notification_email(
                    "member@example.test",
                    "Subject",
                    "Body",
                )
