from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}_{raw}" if prefix else raw


def new_request_id() -> str:
    # Sortable-ish, opaque, safe in headers and logs. 48 bits of millisecond time.
    return f"req_{int(datetime.now(UTC).timestamp() * 1000):012x}{uuid.uuid4().hex[:20]}"


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")
run_id_var: ContextVar[str] = ContextVar("run_id", default="-")
task_id_var: ContextVar[str] = ContextVar("task_id", default="-")


@dataclass
class ContextSnapshot:
    request_id: str
    tenant_id: str
    user_id: str
    run_id: str
    task_id: str


def snapshot() -> ContextSnapshot:
    return ContextSnapshot(
        request_id=request_id_var.get(),
        tenant_id=tenant_id_var.get(),
        user_id=user_id_var.get(),
        run_id=run_id_var.get(),
        task_id=task_id_var.get(),
    )


@contextmanager
def request_context(
    *,
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> Iterator[str]:
    """Set correlation IDs for a unit of work and restore the previous values afterwards."""
    rid = request_id or new_request_id()
    tokens: list[tuple[ContextVar[str], Token[str]]] = [(request_id_var, request_id_var.set(rid))]
    if tenant_id is not None:
        tokens.append((tenant_id_var, tenant_id_var.set(tenant_id)))
    if user_id is not None:
        tokens.append((user_id_var, user_id_var.set(user_id)))
    if run_id is not None:
        tokens.append((run_id_var, run_id_var.set(run_id)))
    if task_id is not None:
        tokens.append((task_id_var, task_id_var.set(task_id)))
    try:
        yield rid
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def bind_run(run_id: str, request_id: str, tenant_id: str, task_id: str | None = None) -> list[Token]:
    tokens = [
        run_id_var.set(run_id),
        request_id_var.set(request_id),
        tenant_id_var.set(tenant_id),
    ]
    if task_id:
        tokens.append(task_id_var.set(task_id))
    return tokens


def unbind(tokens: list[Token]) -> None:
    for var, token in zip(
        [run_id_var, request_id_var, tenant_id_var, task_id_var],
        tokens + [None] * (4 - len(tokens)),
        strict=False,
    ):
        if token is not None:
            var.reset(token)
