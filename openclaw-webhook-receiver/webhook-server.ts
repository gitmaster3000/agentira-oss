/**
 * Embedded HTTP webhook server for the OpenClaw Agentira plugin.
 *
 * Receives structured POST /webhook payloads from the Agentira backend,
 * builds a sanitised prompt (no raw user content — structured fields only),
 * and triggers an agent run via the OpenClaw gateway's completions API.
 *
 * stdlib only — zero external dependencies.
 */

import http from "node:http";
import https from "node:https";

// ── Types ────────────────────────────────────────────────────────────────

interface WebhookPayload {
  event: string;
  task_id?: string;
  task_title?: string;
  project_id?: string;
  project_name?: string;
  status?: string;
  priority?: string;
  actor?: string;
  timestamp?: string;
}

export interface ServerConfig {
  port: number;
  token: string;
  gatewayUrl: string;
  gatewayToken: string;
  agentName: string;
}

export interface WebhookServer {
  start(): Promise<void>;
  stop(): Promise<void>;
}

// ── Prompt builder ───────────────────────────────────────────────────────
// Structured fields only — task titles and comments are user-supplied
// content that must never be concatenated raw into an LLM prompt.

function buildPrompt(payload: WebhookPayload): string {
  const lines: string[] = [];
  const event = payload.event ?? "unknown";

  if (event.startsWith("task.")) {
    lines.push(`# Agentira Event: ${event}`);
    lines.push("");
    if (payload.task_id) lines.push(`Task ID: ${payload.task_id}`);
    if (payload.status) lines.push(`Status: ${payload.status}`);
    if (payload.priority) lines.push(`Priority: ${payload.priority}`);
    if (payload.actor) lines.push(`Triggered by: ${payload.actor}`);
    lines.push("");
    lines.push("## Instructions");
    lines.push(
      "An event occurred on a task assigned to you. " +
        "Use your Agentira tools to inspect the task, understand what is needed, " +
        "and take appropriate action."
    );

    if (event === "task.assigned" || event === "task.created") {
      lines.push(
        "This is a new assignment. Read the task description and begin working on it."
      );
    } else if (event === "task.moved") {
      lines.push(
        `The task status changed to '${payload.status ?? "unknown"}'. ` +
          "Check if further action is needed."
      );
    } else if (event === "task.commented") {
      lines.push(
        "A new comment was added. Read the latest comments and respond or adjust your work."
      );
    } else if (event === "task.updated") {
      lines.push(
        "Task metadata was updated. Re-read the task to check for changed requirements."
      );
    }
  } else if (event.startsWith("project.")) {
    lines.push(`# Agentira Event: ${event}`);
    lines.push("");
    if (payload.project_id) lines.push(`Project ID: ${payload.project_id}`);
    if (payload.actor) lines.push(`Triggered by: ${payload.actor}`);
    lines.push("");
    lines.push("## Instructions");
    lines.push(
      "A project-level event occurred. " +
        "Check your assigned tasks and notifications for details."
    );
  }

  return lines.join("\n");
}

// ── Gateway trigger ──────────────────────────────────────────────────────

function triggerAgent(prompt: string, cfg: ServerConfig): Promise<void> {
  const body = JSON.stringify({
    model: cfg.agentName || "main",
    messages: [{ role: "user", content: prompt }],
  });

  const url = new URL(cfg.gatewayUrl);
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Content-Length": String(Buffer.byteLength(body)),
  };
  if (cfg.gatewayToken) {
    headers["Authorization"] = `Bearer ${cfg.gatewayToken}`;
  }

  return new Promise<void>((resolve, reject) => {
    const mod = url.protocol === "https:" ? https : http;
    const req = mod.request(
      {
        hostname: url.hostname,
        port: url.port || (url.protocol === "https:" ? 443 : 80),
        path: url.pathname + url.search,
        method: "POST",
        headers,
      },
      (res: http.IncomingMessage) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => {
          if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
            console.log(
              `[agentira-webhook] Agent triggered (HTTP ${res.statusCode})`
            );
            resolve();
          } else {
            const text = Buffer.concat(chunks).toString().slice(0, 200);
            console.error(
              `[agentira-webhook] Agent trigger failed HTTP ${res.statusCode}: ${text}`
            );
            reject(new Error(`HTTP ${res.statusCode}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ── Server factory ───────────────────────────────────────────────────────

export function createWebhookServer(config: ServerConfig): WebhookServer {
  let httpServer: http.Server | null = null;

  async function handleWebhook(
    req: http.IncomingMessage,
    res: http.ServerResponse
  ) {
    // Token validation
    if (config.token) {
      const received = (req.headers["x-agentira-token"] as string) ?? "";
      if (received !== config.token) {
        console.warn(
          `[agentira-webhook] Rejected — invalid token from ${req.socket.remoteAddress}`
        );
        res.writeHead(403, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "forbidden" }));
        return;
      }
    }

    // Read body
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk as Buffer);
    const raw = Buffer.concat(chunks).toString();

    let payload: WebhookPayload;
    try {
      payload = JSON.parse(raw);
    } catch {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "invalid JSON" }));
      return;
    }

    console.log(
      `[agentira-webhook] Received: event=${payload.event} task=${payload.task_id ?? "n/a"}`
    );

    // Respond immediately — agent trigger runs async
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true }));

    const prompt = buildPrompt(payload);
    triggerAgent(prompt, config).catch((err) => {
      console.error("[agentira-webhook] Agent trigger error:", err);
    });
  }

  return {
    start() {
      return new Promise<void>((resolve, reject) => {
        httpServer = http.createServer((req, res) => {
          if (req.method === "POST" && req.url === "/webhook") {
            handleWebhook(req, res);
          } else if (req.method === "GET" && req.url === "/health") {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ ok: true, plugin: "agentira-webhook" }));
          } else {
            res.writeHead(404, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "not found" }));
          }
        });
        httpServer.listen(config.port, "0.0.0.0", () => resolve());
        httpServer.on("error", reject);
      });
    },
    stop() {
      return new Promise<void>((resolve) => {
        if (httpServer) {
          httpServer.close(() => resolve());
        } else {
          resolve();
        }
      });
    },
  };
}
