"""Branded HTML layout for transactional emails.

Table-based with inline styles only — the subset every mail client renders
(Gmail, Outlook, Apple Mail). Callers pass plain strings; all of them are
HTML-escaped here.
"""
from html import escape

_BRAND = "#6e56cf"


def render(*, heading: str, paragraphs: list[str], button_label: str = "",
           button_url: str = "", footnote: str = "") -> str:
    body = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:24px;color:#3f3f46;">{escape(p)}</p>'
        for p in paragraphs
    )
    button = ""
    link_fallback = ""
    if button_label and button_url:
        url = escape(button_url, quote=True)
        button = (
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;"><tr>'
            f'<td style="border-radius:8px;background:{_BRAND};">'
            f'<a href="{url}" style="display:inline-block;padding:12px 28px;font-size:15px;'
            'font-weight:600;color:#ffffff;text-decoration:none;border-radius:8px;">'
            f'{escape(button_label)}</a></td></tr></table>'
        )
        link_fallback = (
            '<p style="margin:0;font-size:12px;line-height:18px;color:#71717a;">'
            f'Button not working? Copy this link into your browser:<br>'
            f'<a href="{url}" style="color:{_BRAND};word-break:break-all;">{url}</a></p>'
        )
    note = (
        f'<p style="margin:16px 0 0;font-size:12px;line-height:18px;color:#71717a;">{escape(footnote)}</p>'
        if footnote else ""
    )
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#f4f4f7;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;">'
        '<tr><td align="center" style="padding:32px 16px;">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;">'
        f'<tr><td style="background:{_BRAND};padding:20px 32px;font-size:20px;font-weight:700;'
        'color:#ffffff;letter-spacing:.3px;">Agentira</td></tr>'
        '<tr><td style="padding:32px;">'
        f'<h1 style="margin:0 0 16px;font-size:22px;line-height:30px;color:#18181b;">{escape(heading)}</h1>'
        f'{body}{button}{link_fallback}{note}'
        '</td></tr>'
        '<tr><td style="padding:16px 32px;background:#fafafa;border-top:1px solid #e4e4e7;'
        'font-size:12px;line-height:18px;color:#a1a1aa;">Sent by Agentira. '
        'If you weren\'t expecting this email, you can safely ignore it.</td></tr>'
        '</table></td></tr></table></body></html>'
    )
