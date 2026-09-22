from __future__ import annotations

import importlib
import inspect
from typing import Any, Callable


AUTH_ROUTING_PAYLOAD = "AUTH_ROUTING_PAYLOAD"
CAPABILITY_PAYLOAD = "CAPABILITY_PAYLOAD"
EXECUTION_CONTEXT = "EXECUTION_CONTEXT"


def resolve_registry_executor(binding: str) -> Callable[..., Any]:
    module_name, sep, attr = str(binding or "").rpartition(".")
    if not sep or not module_name or not attr:
        raise PermissionError("Registry executor binding is invalid")
    module = importlib.import_module(module_name)
    executor = getattr(module, attr, None)
    if not callable(executor):
        raise PermissionError("Registry executor binding is not callable")
    actual = (
        f"{getattr(executor, '__module__', '')}."
        f"{getattr(executor, '__name__', '')}"
    )
    if actual != binding:
        raise PermissionError(
            "Resolved executor does not match exact Registry binding"
        )
    return executor


def executor_invocation_contract(executor: Callable[..., Any]) -> str | None:
    params = inspect.signature(executor).parameters
    if {"authorization", "routing_decision", "payload"}.issubset(params):
        return AUTH_ROUTING_PAYLOAD
    if {"capability", "payload"}.issubset(params):
        return CAPABILITY_PAYLOAD
    if "execution_context" in params:
        return EXECUTION_CONTEXT
    return None


def registry_executor_invocation_contract(binding: str) -> str | None:
    try:
        executor = resolve_registry_executor(binding)
    except (ImportError, AttributeError, PermissionError, ValueError):
        return None
    return executor_invocation_contract(executor)


def registry_executor_is_task_adapter_compatible(binding: str | None) -> bool:
    if not str(binding or "").strip():
        return False
    return registry_executor_invocation_contract(str(binding)) is not None
