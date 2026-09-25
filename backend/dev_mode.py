"""Dev-mode switch. AGENTIRA_ENV=dev turns on local-only conveniences (e.g.
password-reset links returned in the API response instead of emailed).

Default is 'prod', so every liberty is fail-safe OFF unless a dev config
explicitly opts in — same gate the dev API-key bypass uses (jwt_auth)."""
import os


def is_dev() -> bool:
    return os.getenv("AGENTIRA_ENV", "prod").strip().lower() == "dev"
