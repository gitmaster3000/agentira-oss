# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13"]
# ///
"""Drive one OpenWorker session using only its token API.

    uv run drive.py [--url http://127.0.0.1:8765] [--token TOKEN] [--model MODEL] [--prompt TEXT]

Steps: health -> set Ollama endpoint -> temp workspace -> WS session -> user_message
-> stream events (auto-answering approvals) until turn_done. Every frame is appended to events.jsonl.
"""
import argparse
import asyncio
import collections
import json
import urllib.request
import uuid

import websockets

PROMPT = (
    "Create a file hello.py that prints 'hello from openworker', run it with python3, "
    "and tell me its output."
)


def http(base, token, method, path, body=None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-OpenWorker-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default="spike-token-123")
    ap.add_argument("--model", default="ollama:qwen3.6:latest")
    ap.add_argument("--ollama-url", default="http://host.docker.internal:11434")
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--out", default="events.jsonl")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()

    print("health:", http(a.url, a.token, "GET", "/v1/health"))
    print("provider:", http(a.url, a.token, "POST", "/v1/providers",
                            {"name": "ollama", "fields": {"base_url": a.ollama_url}}))

    sid = uuid.uuid4().hex[:12]
    tmp = http(a.url, a.token, "POST", "/v1/workspaces/temp", {"session_id": sid, "git": True})
    print("workspace:", tmp)
    workspace = tmp.get("path") or tmp.get("workspace")

    ws_url = a.url.replace("http", "ws", 1) + f"/ws/session/{sid}?agent=code&workspace={workspace}"
    counts = collections.Counter()
    final_text = []
    log = open(a.out, "w")
    async with websockets.connect(ws_url, subprotocols=["openworker", a.token],
                                  max_size=16 * 2**20) as ws:

        async def recv():
            frame = json.loads(await asyncio.wait_for(ws.recv(), a.timeout))
            log.write(json.dumps(frame) + "\n")
            log.flush()
            counts[frame["type"]] += 1
            return frame

        first = await recv()
        assert first["type"] == "ready", first
        print("ready:", json.dumps(first["data"]))

        await ws.send(json.dumps({"type": "user_message", "text": a.prompt, "model": a.model}))
        while True:
            f = await recv()
            t, d = f["type"], f.get("data", {})
            if t == "permission_required":
                print("approval requested:", json.dumps(d)[:200])
                await ws.send(json.dumps({"type": "approval", "decision": "once"}))
            elif t == "assistant_message":
                final_text.append(d.get("text") or d.get("content") or "")
            elif t in ("tool_started", "tool_finished", "error", "input_rejected"):
                print(t, json.dumps(d)[:200])
            elif t == "turn_done":
                break

    print("event counts:", dict(counts))
    print("assistant:", (final_text[-1] if final_text else "")[:500])
    out = http(a.url, a.token, "GET", f"/v1/sessions/{sid}/messages")
    print("session messages persisted:", len(out) if isinstance(out, list) else out.keys())


asyncio.run(main())
