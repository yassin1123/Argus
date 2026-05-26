"""Trace + request logging middleware — Phase 5 / Week 20 / Day 1.

Seeds the :mod:`trace` context at API entry and emits
``request.start`` + ``request.complete`` events around every
request. Downstream code (auth resolver, pipeline orchestrator,
DB queries) inherits the same ``trace_id`` because contextvars
propagate across ``await`` and ``asyncio.create_task`` boundaries.

The trace_id is also written to a response header
(``X-Trace-Id``) so the caller can correlate from the client
side (browser devtools, curl -v) without having to read the
server logs. If the caller supplies their own ``X-Trace-Id``
on the request we honour it — useful for tying a frontend
session to backend logs.

This middleware is installed *before* the existing
:func:`audit_middleware` in :mod:`main` so the audit row is
written inside the trace's context.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from fastapi import Request, Response

from .logging import emit_event
from .trace import (
    TraceContext,
    bind_trace_context,
    new_trace_id,
    set_trace_context,
)


TRACE_HEADER = "X-Trace-Id"


def _client_supplied_trace_id(request: Request) -> str | None:
    """Honour an inbound ``X-Trace-Id`` header iff it looks like
    a sensible identifier. We accept any non-empty token up to 128
    chars (UUIDs are 36; we leave room for opaque trace IDs from
    upstream proxies). Anything else we drop and mint our own."""
    raw = request.headers.get(TRACE_HEADER)
    if not raw:
        return None
    tid = raw.strip()
    if not tid or len(tid) > 128:
        return None
    return tid


async def trace_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Bind a trace context, emit start + complete events, attach
    the trace_id to the response header.

    We use :func:`set_trace_context` + manual reset rather than
    the :func:`bind_trace_context` ``with`` block because the
    audit middleware that runs *inside* this one may want to read
    the same trace_id — both via ``contextvars`` automatic
    propagation. Same effect, less indentation.
    """
    trace_id = _client_supplied_trace_id(request) or new_trace_id()
    ctx = TraceContext(trace_id=trace_id)
    token = set_trace_context(ctx)
    t0 = time.perf_counter()
    method = request.method
    path = request.url.path
    response: Response | None = None
    try:
        emit_event(
            "request.start",
            method=method,
            route=path,
        )
        response = await call_next(request)
        return response
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        emit_event(
            "request.failed",
            level=logging.ERROR,
            duration_ms=elapsed_ms,
            method=method,
            route=path,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        if response is not None:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            emit_event(
                "request.complete",
                duration_ms=elapsed_ms,
                method=method,
                route=path,
                status=response.status_code,
            )
            # Tag the response so a client can correlate. Set last
            # so any handler-side mutation doesn't clobber it.
            try:
                response.headers[TRACE_HEADER] = trace_id
            except Exception:  # noqa: BLE001
                pass
        try:
            from .trace import _trace_ctx
            _trace_ctx.reset(token)
        except Exception:  # noqa: BLE001
            # Best-effort reset — if contextvars has already been
            # torn down (rare; only at process exit) we don't care.
            pass


__all__ = ["TRACE_HEADER", "trace_middleware"]
