from .base import Runtime


class GeminiRuntime(Runtime):
    provider = "gemini"
    default_binary = "gemini"
    env_path_override = "AGENTIRA_GEMINI_PATH"
    capabilities = ()
