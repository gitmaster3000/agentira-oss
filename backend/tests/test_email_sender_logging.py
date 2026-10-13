"""AP-651: email send failures log the stage and the real reason."""
import logging
import smtplib
from unittest.mock import patch

from backend import email_sender


def _env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "me@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret-pw")


def test_auth_rejected_logged_with_code(monkeypatch, caplog):
    _env(monkeypatch)
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"BadCredentials")
        with caplog.at_level(logging.ERROR, logger="agentira.email"):
            assert email_sender.send_email("a@b.com", "s", "b") is False
    assert "authentication rejected" in caplog.text and "535" in caplog.text
    assert "secret-pw" not in caplog.text


def test_disconnect_at_login_hints_credentials(monkeypatch, caplog):
    _env(monkeypatch)
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        with caplog.at_level(logging.ERROR, logger="agentira.email"):
            assert email_sender.send_email("a@b.com", "s", "b") is False
    assert "stage=login" in caplog.text and "likely rejected credentials" in caplog.text
    assert "secret-pw" not in caplog.text
