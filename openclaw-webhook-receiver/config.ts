export interface WebhookReceiverConfig {
  enabled: boolean;
  port: number;
  token: string;
  gatewayUrl: string;
  gatewayToken: string;
  agentName: string;
}

function interpolateEnv(value: string): string {
  return value.replace(/\$\{([^}]+)\}/g, (_, name) => process.env[name] ?? "");
}

export function parseConfig(raw: unknown): WebhookReceiverConfig {
  const cfg = (raw ?? {}) as Record<string, unknown>;
  return {
    enabled: cfg.enabled !== false,
    port: (cfg.port as number) ?? 9112,
    token: interpolateEnv((cfg.token as string) ?? ""),
    gatewayUrl: interpolateEnv(
      (cfg.gatewayUrl as string) ?? "http://127.0.0.1:18789/v1/chat/completions"
    ),
    gatewayToken: interpolateEnv((cfg.gatewayToken as string) ?? ""),
    agentName: (cfg.agentName as string) ?? "",
  };
}
