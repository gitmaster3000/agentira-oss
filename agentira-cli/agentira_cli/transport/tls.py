"""Shared TLS context for all outbound HTTPS/WSS calls.

macOS Python builds (python.org, some pyenv) ship without root CA certs, so the
stdlib ssl default context can't verify Railway's certificate
(CERTIFICATE_VERIFY_FAILED). Back the context with certifi's CA bundle so it
just works everywhere, without the user running 'Install Certificates.command'.
"""
from __future__ import annotations

import ssl


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — certifi missing/broken → system default
        return ssl.create_default_context()
