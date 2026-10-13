"""Run the AgentIRA REST API server."""

import os
import socket

import uvicorn
from backend.rest_api import app  # noqa: F401


def dual_stack_socket(port: int) -> socket.socket:
    """One socket that accepts IPv6 and IPv4. Railway's private network
    resolves the backend to IPv6 first; an IPv4-only bind refused those
    connections. uvicorn's own "::" bind is IPv6-only (asyncio sets
    IPV6_V6ONLY), so build the socket here with V6ONLY off."""
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    return sock


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8111"))
    is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
    if is_prod:
        server = uvicorn.Server(uvicorn.Config("backend.rest_api:app"))
        server.run(sockets=[dual_stack_socket(port)])
    else:
        uvicorn.run("backend.rest_api:app", host="0.0.0.0", port=port, reload=True)
