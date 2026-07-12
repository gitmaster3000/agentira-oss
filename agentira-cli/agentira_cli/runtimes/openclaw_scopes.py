"""Discover operator scopes from the installed OpenClaw package.

The daemon must stay in sync if OpenClaw renames scopes or re-buckets
methods. Prefer a tiny Node probe of OpenClaw's own method-scopes module;
fall back to the last known constant so offline/CI-without-OpenClaw still
works.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from functools import lru_cache

logger = logging.getLogger("agentira.runtime.openclaw_scopes")

WRITE_SCOPE_FALLBACK = "operator.write"
READ_SCOPE_FALLBACK = "operator.read"

# Methods we call for pairing management (contract-tested).
PAIRING_METHODS = frozenset({
    "device.pair.list",
    "device.pair.approve",
    "device.pair.reject",
    "device.pair.remove",
    "device.token.rotate",
    "device.token.revoke",
})

_NODE_DISCOVER = r"""
const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");
function findMethodScopes() {
  const candidates = [];
  try {
    const req = createRequire(process.cwd() + "/");
    const pkg = path.dirname(req.resolve("openclaw/package.json"));
    candidates.push(...fs.readdirSync(path.join(pkg, "dist"))
      .filter(f => f.startsWith("method-scopes-") && f.endsWith(".js"))
      .map(f => path.join(pkg, "dist", f)));
  } catch {}
  try {
    const which = require("child_process").execSync("which openclaw", {encoding:"utf8"}).trim();
    if (which) {
      const real = fs.realpathSync(which);
      const bindir = path.dirname(real);
      for (const rel of ["../lib/node_modules/openclaw/dist", "../../lib/node_modules/openclaw/dist"]) {
        const dist = path.normalize(path.join(bindir, rel));
        if (!fs.existsSync(dist)) continue;
        for (const f of fs.readdirSync(dist)) {
          if (f.startsWith("method-scopes-") && f.endsWith(".js"))
            candidates.push(path.join(dist, f));
        }
      }
    }
  } catch {}
  for (const root of [
    "/opt/homebrew/lib/node_modules/openclaw/dist",
    path.join(process.env.HOME || "", ".openclaw/plugin-runtime-deps"),
  ]) {
    try {
      if (root.includes("plugin-runtime")) {
        if (!fs.existsSync(root)) continue;
        for (const d of fs.readdirSync(root)) {
          const dist = path.join(root, d, "dist");
          if (!fs.existsSync(dist)) continue;
          for (const f of fs.readdirSync(dist)) {
            if (f.startsWith("method-scopes-") && f.endsWith(".js"))
              candidates.push(path.join(dist, f));
          }
        }
      } else if (fs.existsSync(root)) {
        for (const f of fs.readdirSync(root)) {
          if (f.startsWith("method-scopes-") && f.endsWith(".js"))
            candidates.push(path.join(root, f));
        }
      }
    } catch {}
  }
  return candidates.sort().reverse()[0] || null;
}
const file = findMethodScopes();
if (!file) { console.log(JSON.stringify({ ok: false, reason: "not-found" })); process.exit(0); }
const src = fs.readFileSync(file, "utf8");
const writeScope = (src.match(/WRITE_SCOPE\s*=\s*"([^"]+)"/) || [])[1] || "operator.write";
const hasAgent = /"agent"/.test(src);
console.log(JSON.stringify({ ok: true, writeScope, hasAgent, file }));
"""


@lru_cache(maxsize=1)
def discover_write_scope() -> str:
    """Return the scope required for OpenClaw `agent` / write methods."""
    if not shutil.which("node"):
        return WRITE_SCOPE_FALLBACK
    try:
        out = subprocess.run(
            ["node", "-e", _NODE_DISCOVER],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return WRITE_SCOPE_FALLBACK
        data = json.loads(out.stdout.strip().splitlines()[-1])
        if data.get("ok") and data.get("writeScope"):
            return str(data["writeScope"])
    except Exception as exc:
        logger.debug("openclaw scope discovery failed: %s", exc)
    return WRITE_SCOPE_FALLBACK


def default_requested_scopes() -> list[str]:
    write = discover_write_scope()
    scopes = [READ_SCOPE_FALLBACK, write]
    seen: set[str] = set()
    out: list[str] = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
