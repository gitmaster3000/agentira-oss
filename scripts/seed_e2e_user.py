"""Seed the sign-in used by the Playwright browser tests (frontend/e2e).

Run against the isolated e2e stack only (docker-compose.e2e.yml):

    docker compose -p ap-e2e -f docker-compose.e2e.yml exec backend python scripts/seed_e2e_user.py

Credentials default to the values in frontend/e2e/credentials.js and can be
overridden with E2E_USER / E2E_PASSWORD / E2E_EMAIL.
"""
import os

from backend.e2e_seed import ensure_e2e_user

NAME = os.environ.get("E2E_USER", "e2e-admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "e2e-password-1234")
EMAIL = os.environ.get("E2E_EMAIL", "e2e-admin@example.test")

if __name__ == "__main__":
    created = ensure_e2e_user(NAME, PASSWORD, EMAIL)
    print(f"{'created' if created else 'already exists'}: {NAME}")
