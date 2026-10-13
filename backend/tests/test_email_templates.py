"""Transactional emails go out as multipart: plain text + branded HTML."""
from unittest.mock import patch

from backend import email_sender, email_templates


def test_render_escapes_user_text_and_has_button():
    html = email_templates.render(
        heading="Hi <b>x</b>", paragraphs=["a & b"],
        button_label="Go", button_url="https://app/x?a=1&b=2",
    )
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert "a &amp; b" in html
    assert 'href="https://app/x?a=1&amp;b=2"' in html
    assert ">Go<" in html


def test_send_email_attaches_html_alternative(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    sent = []
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.send_message.side_effect = sent.append
        assert email_sender.send_email("a@b.com", "s", "plain", html="<p>hi</p>") is True
    msg = sent[0]
    assert msg.is_multipart()
    assert msg.get_body(("plain",)).get_content().strip() == "plain"
    assert "<p>hi</p>" in msg.get_body(("html",)).get_content()


def test_invite_email_is_html_with_link(monkeypatch):
    with patch.object(email_sender, "send_email", return_value=True) as send:
        email_sender.send_invite_email("n@x.io", "CODE1")
    html = send.call_args.kwargs["html"]
    assert "/signup?invite=CODE1" in html
    assert "/signup?invite=CODE1" in send.call_args.args[2]


def test_reset_and_welcome_are_html(monkeypatch):
    with patch.object(email_sender, "send_email", return_value=True) as send:
        email_sender.send_password_reset_email("n@x.io", "Ann", "TOK")
        assert "/reset-password?token=TOK" in send.call_args.kwargs["html"]
        email_sender.send_welcome_email("n@x.io", "Ann")
        assert "/login" in send.call_args.kwargs["html"]
