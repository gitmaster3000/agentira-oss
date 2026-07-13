"""AP-316: deployment adapter contract.

Public surface: `DeployAdapter`, `Capability`, `DeploymentResult`,
`DeployTargetConfig`, and the `register`/`get_adapter` registry.
"""
from __future__ import annotations

from backend.deploy.contract import (
    Capability,
    DeployTargetConfig,
    DeploymentResult,
    DeploymentStatus,
)
from backend.deploy.adapter import DeployAdapter
from backend.deploy.contract import TargetKind
from backend.deploy.railway import RailwayAdapter
from backend.deploy.registry import get_adapter, register

register(TargetKind.RAILWAY, RailwayAdapter())

__all__ = [
    "RailwayAdapter",
    "Capability",
    "DeployTargetConfig",
    "DeploymentResult",
    "DeploymentStatus",
    "DeployAdapter",
    "get_adapter",
    "register",
]
