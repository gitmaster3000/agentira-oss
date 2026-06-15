"""Seed deterministic MOCK data + a test user for local previews (AP-288).

Run inside the backend container against the LOCAL dev DB:

    docker exec agentira-backend-1 python scripts/seed_test_data.py

Creates (idempotently): a test org, a TEST USER that logs in with
username/password (so previews never need Google OAuth), the org's default
agent team, and a couple of demo projects with an epic + tasks across every
board status. Safe to re-run — it no-ops if the test user already exists.

    login →  preview / preview1234
"""
from __future__ import annotations

from backend.db import init_db, privileged, set_current_org, SessionLocal
from backend.models import Profile
from backend import services

# A dedicated preview identity (its own sandbox org), so it never collides with
# a real local "test"/admin account and previews get a clean, isolated dataset.
TEST_USER = "preview"
TEST_PASSWORD = "preview1234"
TEST_DISPLAY = "Preview User"
TEST_EMAIL = "preview@agentira.dev"

STATUSES = ["backlog", "todo", "in_progress", "review", "done"]
PRIORITIES = ["low", "medium", "high", "critical"]
DEMO_PROJECTS = [
    ("Demo Web App", "Sample project for local previews — a small web app."),
    ("Demo API", "Sample backend project for local previews."),
]


def _existing_test_profile():
    # Privileged so we can find the test user regardless of org/RLS context.
    with privileged(), SessionLocal() as db:
        return db.query(Profile).filter(Profile.name == TEST_USER).first()


def main() -> None:
    init_db()

    if _existing_test_profile():
        print(f"Test user '{TEST_USER}' already exists — mock data seeded. Nothing to do.")
        print(f"login →  {TEST_USER} / {TEST_PASSWORD}")
        return

    # 1. Test org + admin test user via the public invite path (also seeds the
    #    org's default agent team — Conductor, Planner, Reviewer, etc.).
    inv = services.create_invite(role="admin", org_id=None, email=TEST_EMAIL)
    profile = services.accept_invite(
        inv["code"], name=TEST_USER, password=TEST_PASSWORD, display_name=TEST_DISPLAY
    )
    org_id = profile["org_id"]
    print(f"created test user '{TEST_USER}' in org {org_id}")

    # Request-like org context so created rows are stamped to the test org and
    # pass row-level security, exactly as a real session would.
    set_current_org(org_id)

    # 2. Demo projects, each with an epic + tasks across every status.
    for pname, pdesc in DEMO_PROJECTS:
        proj = services.create_project(
            pname, pdesc, actor=TEST_USER, members=[TEST_USER], initial_tasks=[]
        )
        pid = proj["id"]
        epic = services.create_epic(pid, "Sprint 1", "First slice of work.", actor=TEST_USER)
        label = pname.split()[-1].lower()
        for i in range(6):
            services.create_task(
                pid,
                title=f"{label} task {i + 1}",
                description=f"Mock task #{i + 1} for previewing the board.",
                status=STATUSES[i % len(STATUSES)],
                priority=PRIORITIES[i % len(PRIORITIES)],
                tags=["demo", "frontend" if i % 2 == 0 else "backend"],
                epic_id=epic["id"] if i < 4 else None,
                actor=TEST_USER,
            )
        print(f"  seeded project '{pname}' — 1 epic, 6 tasks")

    print("done.")
    print(f"login →  {TEST_USER} / {TEST_PASSWORD}")


if __name__ == "__main__":
    main()
