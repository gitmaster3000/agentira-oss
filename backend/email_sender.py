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

from backend import email_templates

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


def is_configured() -> bool:
    return _cfg() is not None


def app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8111").rstrip("/")


def send_email(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """Send an email (plain text, plus an HTML alternative if given). Returns True if handed to the SMTP server.

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
    if html:
        msg.add_alternative(html, subtype="html")

    stage = "connect"
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
            if cfg["starttls"]:
                stage = "starttls"
                s.starttls()
            if cfg["user"]:
                stage = "login"
                s.login(cfg["user"], cfg["password"])
            stage = "send"
            s.send_message(msg)
        return True
    except smtplib.SMTPAuthenticationError as e:
        log.error(
            "Email to %s failed: SMTP authentication rejected for %s@%s:%s (%s %s) — check SMTP_USER/SMTP_PASS",
            to, cfg["user"], cfg["host"], cfg["port"], e.smtp_code, e.smtp_error,
        )
        return False
    except Exception as e:  # ponytail: broad catch — never fail a request on email
        # smtplib retries AUTH LOGIN after a rejected AUTH PLAIN; Gmail then drops the
        # connection, so a bad password surfaces as SMTPServerDisconnected at "login".
        hint = " (likely rejected credentials: check SMTP_USER/SMTP_PASS)" if stage == "login" and isinstance(e, smtplib.SMTPServerDisconnected) else ""
        log.error(
            "Email to %s failed at stage=%s via %s:%s as %s: %s: %s%s",
            to, stage, cfg["host"], cfg["port"], cfg["user"] or "(no auth)",
            type(e).__name__, e, hint,
        )
        return False


def send_welcome_email(to: str, display_name: str) -> bool:
    link = f"{app_base_url()}/login"
    return send_email(
        to,
        "Welcome to Agentira",
        f"Hi {display_name},\n\n"
        f"Your Agentira account is ready. Sign in at {link}\n\n"
        "— The Agentira team",
        html=email_templates.render(
            heading=f"Welcome, {display_name}!",
            paragraphs=["Your Agentira account is ready. Sign in to get started."],
            button_label="Sign in", button_url=link,
        ),
    )


def send_invite_email(to: str, code: str) -> bool:
    link = f"{app_base_url()}/signup?invite={code}"
    return send_email(
        to,
        "You're invited to Agentira",
        "You've been invited to join a workspace on Agentira.\n\n"
        f"Create your account here (link valid for 14 days):\n{link}\n\n"
        "— The Agentira team",
        html=email_templates.render(
            heading="You're invited to Agentira",
            paragraphs=["You've been invited to join a workspace on Agentira. "
                        "Create your account to get started."],
            button_label="Accept invite", button_url=link,
            footnote="This invite link is valid for 14 days.",
        ),
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
        html=email_templates.render(
            heading="Reset your password",
            paragraphs=[f"Hi {display_name},",
                        "We received a request to reset your Agentira password. "
                        "Use the button below to choose a new one."],
            button_label="Reset password", button_url=link,
            footnote="This link is valid for 1 hour. If you didn't request a reset, you can ignore this email.",
        ),
    )
