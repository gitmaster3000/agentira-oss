"""AP-306: transactional email via stdlib smtplib.

Config is read from env (Railway secrets):
    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS,
    SMTP_FROM (falls back to SMTP_USER), SMTP_STARTTLS (default "1"),
    APP_BASE_URL (for links in emails, e.g. https://app.agentira.com)

If SMTP_HOST is unset the sender is a no-op that logs and returns False —
so dev/test and unconfigured deploys don't crash on send. Callers treat a
False return as "not delivered" and never fail the surrounding request.
"""
import os
import smtplib
import logging
from email.message import EmailMessage

log = logging.getLogger("agentira.email")


def _cfg() -> dict | None:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return None
    user = os.getenv("SMTP_USER", "").strip()
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": os.getenv("SMTP_PASS", ""),
        "sender": os.getenv("SMTP_FROM", "").strip() or user,
        "starttls": os.getenv("SMTP_STARTTLS", "1") != "0",
    }


def app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8111").rstrip("/")


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if handed to the SMTP server.

    Never raises on delivery failure — logs and returns False so the caller
    (signup, password reset) doesn't break on a flaky mail server."""
    if not to:
        return False
    cfg = _cfg()
    if cfg is None:
        log.warning("SMTP not configured (SMTP_HOST unset) — skipping email to %s (%s)", to, subject)
        return False

    msg = EmailMessage()
    msg["From"] = cfg["sender"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
            if cfg["starttls"]:
                s.starttls()
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return True
    except Exception as e:  # ponytail: broad catch — never fail a request on email
        log.error("Failed to send email to %s: %s", to, e)
        return False


def send_welcome_email(to: str, display_name: str) -> bool:
    return send_email(
        to,
        "Welcome to Agentira",
        f"Hi {display_name},\n\n"
        f"Your Agentira account is ready. Sign in at {app_base_url()}/login\n\n"
        "— The Agentira team",
    )


def send_password_reset_email(to: str, display_name: str, token: str) -> bool:
    link = f"{app_base_url()}/reset-password?token={token}"
    return send_email(
        to,
        "Reset your Agentira password",
        f"Hi {display_name},\n\n"
        f"Reset your password using this link (valid for 1 hour):\n{link}\n\n"
        "If you didn't request this, you can ignore this email.\n\n"
        "— The Agentira team",
    )
