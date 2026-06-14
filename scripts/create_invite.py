"""Operator script: mint an invite code.

Admin invite (default) → on accept, creates a NEW org and the invitee becomes
its admin. Member invite → joins an existing org (admin normally does this
in-app, but it's here for ops).

Usage:
  AGENTIRA_DB_URL=postgresql://postgres:...@host:port/railway \\
  FRONTEND_URL=https://flowty-frontend-production.up.railway.app \\
  python scripts/create_invite.py --role admin [--email someone@x.com]
  python scripts/create_invite.py --role member --org <org_id>
"""
import argparse
import os

os.environ.setdefault("JWT_SECRET", "operator-script")

from backend import services  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--role", choices=["admin", "member"], default="admin")
p.add_argument("--org", default=None, help="org_id (required for member role)")
p.add_argument("--email", default=None)
args = p.parse_args()

inv = services.create_invite(role=args.role, org_id=args.org, email=args.email,
                             invited_by="operator")
code = inv["code"]
frontend = os.environ.get("FRONTEND_URL", "").rstrip("/")
link = f"{frontend}/signup?invite={code}" if frontend else f"(set FRONTEND_URL) invite={code}"
print(f"role:    {inv['role']}")
print(f"org_id:  {inv['org_id']}")
print(f"expires: {inv['expires_at']}")
print(f"code:    {code}")
print(f"link:    {link}")
