/**
 * OpenClaw plugin: Agentira Webhook Receiver
 *
 * Pattern A2 from the Agentira continuous-execution architecture —
 * OpenClaw receives webhook events natively, without the Python daemon wrapper.
 *
 * Flow:
 *   Agentira backend  ──POST /webhook──►  this plugin  ──/v1/chat/completions──►  OpenClaw gateway
 *
 * The plugin starts an embedded HTTP server on the configured port.
 * When the Agentira backend fires a webhook (task.assigned, task.moved, etc.),
 * the plugin constructs a sanitised prompt from the structured payload and
 * triggers an agent run via the gateway's completions API.
 *
 * Zero external dependencies — Node.js stdlib only.
 */

import { parseConfig } from "./config.js";
import { createWebhookServer, type WebhookServer } from "./webhook-server.js";

export default function (api: any) {
  const config = parseConfig(api.pluginConfig);
  let server: WebhookServer | null = null;

  api.registerService({
    id: "agentira-webhook",

    async start() {
      if (!config.enabled) {
        console.log("[agentira-webhook] Disabled by config");
        return;
      }

      server = createWebhookServer({
        port: config.port,
        token: config.token,
        gatewayUrl: config.gatewayUrl,
        gatewayToken: config.gatewayToken,
        agentName: config.agentName,
      });

      await server.start();

      const auth = config.token ? "token auth" : "no auth (localhost-safe)";
      console.log(
        `[agentira-webhook] Listening on :${config.port} — ${auth}`
      );
    },

    async stop() {
      if (server) {
        await server.stop();
        console.log("[agentira-webhook] Stopped");
      }
    },
  });
}
