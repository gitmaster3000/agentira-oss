# Proof: minimal Claude config for dispatched agents

Real `claude` (2.1.x) run, prompt "say ok", max-turns 1, cwd /tmp, empty Agentira bundle (`{"mcpServers":{}}`). Script: build_args() output vs old flag set.

## Before (old flags: no strict, user settings loaded)
- plugins: frontend-design, caveman, design, productivity, cowork-plugin-management, cc-plugin-agents-md, cc-plugin-telemetry
- mcp_servers (18): plugin:design:{slack,figma,linear,asana,atlassian,notion,intercom,google calendar,gmail}, plugin:productivity:{monday,clickup,google calendar,gmail}, agentira, claude.ai {Claude Docs, Google Calendar, Google Drive, Gmail}
- tools 83, skills 51, cache_creation 16854

## After (ClaudeRuntime.build_args: --strict-mcp-config --setting-sources project,local --settings <rtk hook>)
- plugins: cc-plugin-agents-md, cc-plugin-telemetry, cc-plugin-plugin-authoring (built-in, not personal)
- mcp_servers: [] (only the dispatch bundle would load; no gmail/drive/calendar)
- tools 24, skills 17, cache_creation 5431 (< 15K target)

Tests: `pytest agentira-cli/tests/test_allowed_tools.py test_runtime_adapter_contract.py test_codex_adapter.py test_grok_adapter.py` → 77 passed.

Not done: codex runtime (~/.codex MCP merge can't be stripped via `-c`; needs isolated CODEX_HOME — follow-up). No new per-agent extras UI: extras remain the existing per-agent mcp_servers/mcp_config_override merged into the bundle (default empty).
