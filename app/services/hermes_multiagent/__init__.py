"""Hermes multi-agent runtime adapter subordinated to the DeepSeek Harness."""

from .contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionResult,
    HermesMissionExecutionSpec,
    HermesRuntimeProfile,
)

__all__ = [
    "HERMES_RUNTIME_CAPABILITY_ID",
    "HermesMissionExecutionResult",
    "HermesMissionExecutionSpec",
    "HermesRuntimeProfile",
]
