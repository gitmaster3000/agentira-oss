"""Run the AgentIRA REST API server."""

import os
import uvicorn
from backend.rest_api import app  # noqa: F401

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8111"))
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
    # Bind dual-stack: "::" accepts IPv6 (Railway private networking is
    # IPv6-only) AND IPv4 (public domain), so MCP can reach us over
    # *.railway.internal without dropping public access. Override via HOST
    # if a platform ever needs IPv4-only.
    host = os.getenv("HOST", "::")
    uvicorn.run("backend.rest_api:app", host=host, port=port, reload=not is_prod)
