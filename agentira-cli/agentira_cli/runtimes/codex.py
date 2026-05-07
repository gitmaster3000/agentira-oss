from .base import Runtime


class CodexRuntime(Runtime):
    provider = "codex"
    default_binary = "codex"
    env_path_override = "AGENTIRA_CODEX_PATH"
    capabilities = ("stream_json", "resume")
