"""AP-316: adapter registry — one `DeployAdapter` instance per `kind`.

AP-317 (docker) and AP-318 (railway) register themselves here; nothing in
this module knows about a specific target kind.
"""
from __future__ import annotations

from backend.deploy.adapter import DeployAdapter
from backend.deploy.contract import TargetKind

_REGISTRY: dict[TargetKind, DeployAdapter] = {}


def register(kind: TargetKind, adapter: DeployAdapter) -> None:
    _REGISTRY[kind] = adapter


def get_adapter(kind: TargetKind) -> DeployAdapter:
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise LookupError(f"no adapter registered for kind={kind.value!r}") from None
