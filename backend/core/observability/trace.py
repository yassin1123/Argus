"""Trace context — Phase 5 / Week 20 / Day 1.

A `contextvars`-backed bag of correlation IDs (``trace_id``,
``run_id``, ``session_id``, ``firm_id``, ``actor_id``,
``stage``) that propagates across async boundaries without
threading params through every function signature. The
FastAPI middleware seeds it at API entry. The pipeline reads
from it when emitting structured events so a request and the
agent stages it triggers share one ``trace_id``.

Why ``contextvars``: ``asyncio`` propagates them automatically
across ``await`` points and across ``asyncio.create_task`` /
``gather`` / ``TaskGroup`` boundaries (Python 3.7+). We don't
have to wrap every coroutine or pass a "ctx" param around.

For background workers (Celery) we expose
:func:`bind_trace_context` so the task body can re-bind whatever
the producer sent in the task payload — keeping the request-side
trace_id intact across the queue hop.

There is *no* fall-back module-level "default trace_id". When
nothing is bound we return ``None`` for every field — callers
either generate their own (e.g. the pipeline kick-off path
outside HTTP) or accept that the log line just won't carry a
trace_id. We refuse to invent one silently because that hides
bugs.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Iterator


@dataclass(frozen=True)
class TraceContext:
    """Immutable snapshot of correlation IDs in scope."""

    trace_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    firm_id: str | None = None
    actor_id: str | None = None
    stage: str | None = None

    def as_log_fields(self) -> dict[str, str]:
        """Return the non-None fields keyed for the log envelope.
        Drops ``None`` so the log line stays compact when a field
        isn't applicable (e.g. ``firm_id`` on an unauthenticated
        health-check)."""
        out: dict[str, str] = {}
        if self.trace_id:
            out["trace_id"] = self.trace_id
        if self.run_id:
            out["run_id"] = self.run_id
        if self.session_id:
            out["session_id"] = self.session_id
        if self.firm_id:
            out["firm_id"] = self.firm_id
        if self.actor_id:
            out["actor_id"] = self.actor_id
        if self.stage:
            out["stage"] = self.stage
        return out


_EMPTY = TraceContext()
_trace_ctx: ContextVar[TraceContext] = ContextVar(
    "argus_trace_context", default=_EMPTY,
)


def new_trace_id() -> str:
    """Mint a fresh trace_id. UUID4 — 122 bits of entropy is fine
    for in-flight correlation, no DB lookup needed to disambiguate
    against historical ones."""
    return str(uuid.uuid4())


def new_run_id() -> str:
    """Mint a fresh run_id. Distinct from trace_id so a single
    pipeline run that fans out to multiple sub-traces (e.g. retry,
    background refresh) can still be grouped by run_id while each
    sub-flow keeps its own trace_id."""
    return str(uuid.uuid4())


def get_trace_context() -> TraceContext:
    """Return the trace context bound in the current async task,
    or an empty :class:`TraceContext` when nothing is bound. Never
    returns ``None`` — callers can safely read attributes."""
    return _trace_ctx.get()


def set_trace_context(ctx: TraceContext) -> Token[TraceContext]:
    """Replace the bound context. Returns the previous-value token
    so the caller can reset() it later (the middleware pattern)."""
    return _trace_ctx.set(ctx)


@contextmanager
def bind_trace_context(
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    firm_id: str | None = None,
    actor_id: str | None = None,
    stage: str | None = None,
    inherit: bool = True,
) -> Iterator[TraceContext]:
    """Context-manager that binds (a merged-with-current) trace
    context for the duration of the ``with`` block.

    ``inherit=True`` (the default) merges the kwargs on top of the
    current context — so e.g. the pipeline can scope a ``stage``
    without losing the request-seeded trace_id / firm_id. Pass
    ``inherit=False`` to start from a clean :class:`TraceContext`
    (rare — typically only the API middleware or a Celery task
    head, where the producer's context is being replayed
    explicitly).
    """
    base = _trace_ctx.get() if inherit else _EMPTY
    merged = replace(
        base,
        trace_id=trace_id if trace_id is not None else base.trace_id,
        run_id=run_id if run_id is not None else base.run_id,
        session_id=session_id if session_id is not None else base.session_id,
        firm_id=firm_id if firm_id is not None else base.firm_id,
        actor_id=actor_id if actor_id is not None else base.actor_id,
        stage=stage if stage is not None else base.stage,
    )
    token = _trace_ctx.set(merged)
    try:
        yield merged
    finally:
        _trace_ctx.reset(token)


__all__ = [
    "TraceContext",
    "bind_trace_context",
    "get_trace_context",
    "new_run_id",
    "new_trace_id",
    "set_trace_context",
]
