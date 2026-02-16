"""Run the AgentIRA REST API server."""

import uvicorn
from backend.rest_api import app  # noqa: F401

if __name__ == "__main__":
    uvicorn.run("backend.rest_api:app", host="0.0.0.0", port=8111, reload=True)
