"""
Proxy that fixes ZeroClaw's missing Sec-WebSocket-Protocol echo
AND stubs unimplemented API routes that return SPA HTML.

Usage: python ws_proxy.py <listen_port> <target_port>
"""
import asyncio
import json
import re
import sys

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3011
TARGET_HOST = "127.0.0.1"
TARGET_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3015

# ── API stubs for unimplemented ZeroClaw gateway routes ──────────────
# The gateway serves SPA index.html for unknown paths, but the dashboard
# JS expects JSON from these API endpoints.

_STUB_ROUTES = {
    "/api/integrations/settings": {"integrations": []},
}


def _match_stub(request_line: str) -> str | None:
    """Return JSON stub if request targets a stubbed route, else None."""
    for route, body in _STUB_ROUTES.items():
        if route in request_line:
            return json.dumps(body)
    return None


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _read_until_headers(reader) -> bytes:
    """Read bytes until we see \\r\\n\\r\\n (end of HTTP headers)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = await reader.read(4096)
        if not chunk:
            break
        buf += chunk
    return buf


async def handle(client_reader, client_writer):
    # Read the initial HTTP request
    request_buf = await _read_until_headers(client_reader)
    if not request_buf:
        client_writer.close()
        return

    request_line = request_buf.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
    is_ws = b"Upgrade: websocket" in request_buf or b"upgrade: websocket" in request_buf

    # ── Check if this request needs a stub response ──────────────────
    stub_json = _match_stub(request_line)
    if stub_json and not is_ws:
        body = stub_json.encode("utf-8")
        resp = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        client_writer.write(resp)
        await client_writer.drain()
        client_writer.close()
        return

    # ── Connect to ZeroClaw ──────────────────────────────────────────
    try:
        target_reader, target_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except Exception:
        client_writer.close()
        return

    # Rewrite Host and Origin headers to match target port
    request_buf = re.sub(
        rb"Host: localhost:\d+", b"Host: localhost:" + str(TARGET_PORT).encode(), request_buf
    )
    request_buf = re.sub(
        rb"Origin: http://localhost:\d+", b"Origin: http://localhost:" + str(TARGET_PORT).encode(), request_buf
    )

    # ── WebSocket upgrade: inject Sec-WebSocket-Protocol, then pipe ──
    if is_ws:
        m = re.search(rb"Sec-WebSocket-Protocol:\s*([^\r\n]+)", request_buf, re.IGNORECASE)
        protocol_value = m.group(1).strip() if m else None

        target_writer.write(request_buf)
        await target_writer.drain()

        if protocol_value:
            response_buf = await _read_until_headers(target_reader)
            if b"sec-websocket-protocol" not in response_buf.lower():
                response_buf = response_buf.replace(
                    b"\r\n\r\n",
                    b"\r\nSec-WebSocket-Protocol: " + protocol_value + b"\r\n\r\n",
                    1,
                )
            client_writer.write(response_buf)
            await client_writer.drain()

        # Full-duplex pipe for WebSocket frames
        await asyncio.gather(
            pipe(client_reader, target_writer),
            pipe(target_reader, client_writer),
        )
        return

    # ── Regular HTTP: force Connection: close so browser makes fresh ─
    # connections for each request (lets us intercept every request).
    request_buf = re.sub(
        rb"Connection: keep-alive",
        b"Connection: close",
        request_buf,
        flags=re.IGNORECASE,
    )

    target_writer.write(request_buf)
    await target_writer.drain()

    # Pipe the response back and close
    await pipe(target_reader, client_writer)

    try:
        target_writer.close()
    except Exception:
        pass


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", LISTEN_PORT)
    print(f"Proxy running: http://localhost:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}")
    print(f"Open the dashboard at http://localhost:{LISTEN_PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
