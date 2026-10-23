"""Dedicated sign-in for the Playwright browser tests (frontend/e2e).

Goes through the public invite path, so the user is a normal org admin in its
own fresh org (with the default agent team). Throwaway credentials for a
throwaway test database — never point this at a real deployment.
"""
from backend import services


def ensure_e2e_user(name: str, password: str, email: str) -> bool:
    """Create the e2e admin if it can't already sign in. Returns True if created."""
    if services.authenticate_user(name, password):
        return False
    inv = services.create_invite(role="admin", org_id=None, email=email,
                                 invited_by="e2e-seed")
    services.accept_invite(inv["code"], name=name, password=password,
                           display_name="E2E Admin", email=email)
    return True
