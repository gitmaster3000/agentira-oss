"""One-shot operator script: provision the non-superuser app role so Postgres
RLS actually applies to request-path queries.

What it does (idempotent):
  1. CREATE ROLE agentira_app LOGIN with the given password (or update it).
  2. GRANT USAGE on schema public + CRUD on all current/future tables.
  3. Print the AGENTIRA_APP_DB_URL to set on the flowty-api service.

The RLS policies themselves (ENABLE/FORCE ROW LEVEL SECURITY + CREATE POLICY)
are applied by run_migrations() on every boot — this script only creates the
role they key on, which needs a password we don't bake into the image.

Usage:
  AGENTIRA_DB_URL=postgresql://postgres:...@host:port/railway \\
  APP_ROLE_PASSWORD=<choose-a-strong-one> \\
  python scripts/setup_rls.py
"""
import os
import sys
from sqlalchemy import create_engine, text

SUPER_URL = os.environ["AGENTIRA_DB_URL"]
APP_ROLE = "agentira_app"
APP_PW = os.environ.get("APP_ROLE_PASSWORD")
if not APP_PW:
    sys.exit("Set APP_ROLE_PASSWORD to a strong secret.")

eng = create_engine(SUPER_URL, future=True)
with eng.begin() as c:
    exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"),
                       {"r": APP_ROLE}).first()
    if exists:
        c.execute(text(f"ALTER ROLE {APP_ROLE} WITH LOGIN PASSWORD :pw"),
                  {"pw": APP_PW})
        print(f"role {APP_ROLE} exists — password updated")
    else:
        c.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD :pw"),
                  {"pw": APP_PW})
        print(f"created role {APP_ROLE}")

    # Schema + table privileges. RLS still restricts scoped tables row-wise;
    # these grants only open the tables to the role at all.
    c.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
    c.execute(text(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        f"TO {APP_ROLE}"))
    c.execute(text(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"))
    # Future tables created by create_all on later deploys.
    c.execute(text(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"))
    c.execute(text(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"))
    print("granted schema + table privileges")

# Build the app connection URL by swapping credentials in the superuser URL.
from urllib.parse import urlsplit, urlunsplit
parts = urlsplit(SUPER_URL)
hostport = parts.netloc.split("@", 1)[-1]
app_netloc = f"{APP_ROLE}:{APP_PW}@{hostport}"
app_url = urlunsplit((parts.scheme, app_netloc, parts.path, parts.query, parts.fragment))
print("\nSet this on flowty-api (private host for in-cluster use):")
print(f"  AGENTIRA_APP_DB_URL={app_url}")
