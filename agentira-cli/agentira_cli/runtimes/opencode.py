from .base import Runtime


class OpenCodeRuntime(Runtime):
    provider = "opencode"
    default_binary = "opencode"
    env_path_override = "AGENTIRA_OPENCODE_PATH"
    capabilities = ("stream_json",)
