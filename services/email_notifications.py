import os
import ssl
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

from flask import current_app, has_app_context


def send_notification_email(recipient, subject, body):
    if has_app_context() and current_app.testing:
        return False
    if os.environ.get("SKILLSWAP_EMAIL_ENABLED", "").strip().lower() != "true":
        return False

    host = os.environ.get("SKILLSWAP_SMTP_HOST")
    sender = os.environ.get("SKILLSWAP_EMAIL_FROM")
    if not host or not sender:
        raise RuntimeError(
            "SKILLSWAP_SMTP_HOST and SKILLSWAP_EMAIL_FROM are required when email is enabled."
        )
    sender_address = parseaddr(sender)[1]
    if not sender_address or "@" not in sender_address:
        raise RuntimeError("SKILLSWAP_EMAIL_FROM must contain a valid email address.")
    try:
        port = int(os.environ.get("SKILLSWAP_SMTP_PORT", "587"))
    except ValueError as error:
        raise RuntimeError("SKILLSWAP_SMTP_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("SKILLSWAP_SMTP_PORT must be between 1 and 65535.")

    username = os.environ.get("SKILLSWAP_SMTP_USERNAME")
    password = os.environ.get("SKILLSWAP_SMTP_PASSWORD")
    if bool(username) != bool(password):
        raise RuntimeError(
            "Both SKILLSWAP_SMTP_USERNAME and SKILLSWAP_SMTP_PASSWORD are required for SMTP authentication."
        )

    email = EmailMessage()
    email["From"] = sender
    email["To"] = recipient
    email["Subject"] = subject
    email.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        if username and password:
            smtp.login(username, password)
        refused_recipients = smtp.send_message(email)
        if refused_recipients:
            raise smtplib.SMTPRecipientsRefused(refused_recipients)
    return True
