"""Run the AgentIRA REST API server."""

import os
import uvicorn
from backend.rest_api import app  # noqa: F401

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8111"))
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
    uvicorn.run("backend.rest_api:app", host="0.0.0.0", port=port, reload=not is_prod)
