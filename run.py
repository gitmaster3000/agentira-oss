"""Run the AgentIRA REST API server."""

import os
import uvicorn
from backend.rest_api import app  # noqa: F401

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8111"))
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
    # "::" listens on IPv6 and IPv4. Railway's private network resolves the
    # backend to an IPv6 address first; an IPv4-only bind refused every such
    # connection and nginx had to retry over IPv4.
    host = os.getenv("HOST", "::" if is_prod else "0.0.0.0")
    uvicorn.run("backend.rest_api:app", host=host, port=port, reload=not is_prod)
