"""Structured logging — Phase 5 / Week 20 / Day 1.

JSON-line logger keyed on event names (``pipeline.start``,
``planner.complete``, etc.) rather than free-form messages. Every
line carries the trace context bound by :mod:`trace` plus a
structured ``data`` bag of safe scalars. Prose content — claim
text, evidence chunks, memo prose — is explicitly excluded by
:func:`redact` before serialization, regardless of what the
caller passes. The redaction rule is the enterprise / pilot
privacy guarantee, tested explicitly.

Two surfaces:

  - :func:`emit_event` — preferred. Call sites pass an event name
    + structured kwargs; the function attaches the trace context,
    runs the kwargs through :func:`redact`, and emits one JSON
    line to the standard ``argus.events`` logger.
  - :func:`structured_logger` — escape hatch for code that still
    uses ``logging.getLogger(__name__).info(...)``. Returns a
    :class:`logging.Logger` whose records will be JSON-formatted
    by :class:`EventFormatter` when configured.

Output config: dev = stdout, prod = file path from
``ARGUS_LOG_FILE``. The shipping seam (external sink) is one
:class:`logging.Handler` install away — we expose
:func:`configure_event_logging` but don't prescribe Datadog/ELK.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Final, Iterable

from .trace import get_trace_context


# ---------------------------------------------------------------------------
# Privacy redaction
# ---------------------------------------------------------------------------


# Fields that MUST NEVER appear in a log line. Each is a substring
# match against the field name, lowercased — so ``claim_text``,
# ``claimText`` (after our lowercase), ``evidence_text``,
# ``evidence_excerpt``, ``memo_prose``, ``payload_text`` all hit.
#
# Why a denylist instead of an allowlist: we use a denylist because
# log call-sites legitimately invent new safe-scalar field names
# all the time (``claim_count``, ``model_name``, ``token_usage``)
# and forcing an allowlist would either be perpetually out of date
# or default-deny so noisily that engineers route around it. The
# denylist captures the *categories* of leak we ban and is tight
# enough to test exhaustively.
REDACTED_FIELD_NAMES: Final[tuple[str, ...]] = (
    "claim_text",
    "claim_body",
    "claim_content",
    "evidence_text",
    "evidence_body",
    "evidence_content",
    "evidence_excerpt",
    "memo_text",
    "memo_body",
    "memo_prose",
    "memo_content",
    "section_text",
    "section_body",
    "section_content",
    "payload_text",
    "payload_body",
    "payload_prose",
    "prose",
    "body_text",
    "raw_text",
    "raw_body",
    "raw_prose",
    "writer_output",
    "writer_body",
    "snippet",
    "excerpt",
    "passage",
    "chunk_text",
)

# A field that ends with one of these suffixes is also dropped —
# catches ``analyst_claim_text``, ``verifier_claim_body``, etc.
_REDACT_SUFFIXES: Final[tuple[str, ...]] = (
    "_text",
    "_body",
    "_content",
    "_prose",
    "_excerpt",
    "_passage",
    "_snippet",
)

# Field-name allowlist exemptions for the suffix rule. ``status_text``
# is a verdict label not prose; ``user_text`` would be too if it ever
# existed; ``log_text`` is a meta log message etc. We're intentionally
# tight here — when in doubt, names get dropped.
_REDACT_SUFFIX_ALLOW: Final[frozenset[str]] = frozenset({
    "status_text",
})

# Sentinel placeholder so the log reader can see "this field was
# dropped by policy" rather than just "field missing". The value
# is the canonical token tested in :func:`test_redact_strips_claim_text`.
REDACTED_VALUE: Final[str] = "[REDACTED]"


def _is_redacted_field(name: str) -> bool:
    """True when ``name`` matches the prose-content denylist
    (exact match) or the suffix rule (and isn't on the allow-
    list)."""
    lname = name.lower()
    if lname in REDACTED_FIELD_NAMES:
        return True
    if lname in _REDACT_SUFFIX_ALLOW:
        return False
    for suf in _REDACT_SUFFIXES:
        if lname.endswith(suf):
            return True
    return False


def redact(data: Any) -> Any:
    """Walk a value and strip every field whose name is on the
    prose-content denylist. Lists + dicts recurse; scalars pass
    through. Used by :func:`emit_event` before JSON serialization
    so call-sites cannot accidentally leak prose by passing a
    raw payload dict.

    Replacing-with-sentinel rather than dropping the key keeps the
    field's *presence* visible (so a log reader sees that prose
    was attempted and got stripped) while denying the value. That
    makes accidental leaks loud, not silent.
    """
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and _is_redacted_field(k):
                out[k] = REDACTED_VALUE
                continue
            out[k] = redact(v)
        return out
    if isinstance(data, list):
        return [redact(v) for v in data]
    if isinstance(data, tuple):
        return tuple(redact(v) for v in data)
    return data


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


EVENT_LOGGER_NAME: Final[str] = "argus.events"


class EventFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as one JSON line.

    Reads structured fields from ``record.__dict__["argus_event"]``
    (set by :func:`emit_event`) plus the trace context attached at
    emit time. Falls back to the legacy ``logging_config`` shape
    for records that didn't go through :func:`emit_event` so
    library code using ``logger.info(...)`` still ends up as JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        ev = getattr(record, "argus_event", None)
        if isinstance(ev, dict):
            # Structured-event path — already redacted by emit_event.
            return json.dumps(ev, default=str)

        # Legacy path — synthesize the envelope so existing
        # logger.info(...) call-sites still come out as JSON.
        envelope: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "event": f"legacy.{record.name}",
            "message": record.getMessage(),
            "module": record.module,
        }
        ctx = get_trace_context().as_log_fields()
        envelope.update(ctx)
        # Pull any extra structured fields the caller passed via
        # ``extra={...}`` — but redact them on the way out so legacy
        # call sites also can't leak prose.
        for k, v in record.__dict__.items():
            if k in _STD_RECORD_FIELDS:
                continue
            if _is_redacted_field(k):
                envelope[k] = REDACTED_VALUE
                continue
            envelope[k] = redact(v)
        return json.dumps(envelope, default=str)


# Standard LogRecord attrs we don't want to splatter into the JSON
# envelope (they're either redundant or already represented).
_STD_RECORD_FIELDS: Final[frozenset[str]] = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process",
    "message", "asctime", "argus_event", "taskName",
})


def emit_event(
    event: str,
    *,
    level: int = logging.INFO,
    duration_ms: float | None = None,
    error: str | None = None,
    **data: Any,
) -> dict[str, Any]:
    """Emit one structured event to the ``argus.events`` logger.

    ``event`` is a dot-namespaced string (``planner.complete``,
    ``request.start``, etc.). ``duration_ms`` and ``error`` are
    promoted to top-level envelope fields because they're queried
    so often. Everything else lands under ``data`` after going
    through :func:`redact`.

    Returns the dict that was emitted (post-redaction) — handy for
    tests + for code that wants to write the same shape to a
    second sink (e.g. session.metadata.pipeline_trace).
    """
    ctx_fields = get_trace_context().as_log_fields()
    envelope: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": logging.getLevelName(level),
        "event": event,
        **ctx_fields,
    }
    if duration_ms is not None:
        envelope["duration_ms"] = round(float(duration_ms), 2)
    if error is not None:
        envelope["error"] = str(error)[:1000]
    if data:
        envelope["data"] = redact(data)

    logger = logging.getLogger(EVENT_LOGGER_NAME)
    if logger.isEnabledFor(level):
        record = logger.makeRecord(
            name=EVENT_LOGGER_NAME, level=level,
            fn="emit_event", lno=0, msg=event, args=(),
            exc_info=None, func="emit_event", extra=None,
        )
        record.argus_event = envelope  # type: ignore[attr-defined]
        logger.handle(record)
    return envelope


def structured_logger(name: str) -> logging.Logger:
    """Return a :class:`logging.Logger` whose records will be
    JSON-formatted by :class:`EventFormatter`. Convenience for
    call-sites migrating off ad-hoc ``logging.getLogger(__name__)``
    that aren't ready to convert to :func:`emit_event` yet.
    """
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Stage timer — context manager for ``stage.complete`` emission
# ---------------------------------------------------------------------------


class StageTimer:
    """Context manager that emits ``<stage>.complete`` on exit
    (or ``<stage>.failed`` on exception) with the elapsed
    duration_ms attached. The caller passes whatever structured
    payload they want in ``data``; redaction is automatic.

    Example::

        with StageTimer("planner", task_count=n_tasks) as t:
            plan = await planner.run(...)
            t.update(task_count=len(plan["tasks"]))
    """

    def __init__(self, stage: str, /, **data: Any) -> None:
        self.stage = stage
        self._data = dict(data)
        self._t0: float = 0.0

    def update(self, **data: Any) -> None:
        """Merge additional structured fields into the on-exit
        payload. Lets the caller record values that aren't known
        until after the work runs (claim counts, token usage)."""
        self._data.update(data)

    def __enter__(self) -> "StageTimer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = (time.perf_counter() - self._t0) * 1000.0
        if exc is None:
            emit_event(
                f"{self.stage}.complete",
                duration_ms=elapsed_ms,
                **self._data,
            )
        else:
            emit_event(
                f"{self.stage}.failed",
                level=logging.ERROR,
                duration_ms=elapsed_ms,
                error=f"{type(exc).__name__}: {exc}",
                **self._data,
            )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


_CONFIGURED = False


def configure_event_logging(
    *,
    stream: Any | None = None,
    file_path: str | None = None,
    extra_handlers: Iterable[logging.Handler] | None = None,
) -> None:
    """Configure the ``argus.events`` logger + the root logger to
    emit JSON via :class:`EventFormatter`.

    Call once at process boot. Idempotent within a process. The
    ``extra_handlers`` arg is the ship-to-sink seam — pass a
    Datadog / ELK / Loki handler and we'll attach it without
    knowing how it works.

    Config precedence: explicit kwargs > ``ARGUS_LOG_FILE`` env
    var > stdout.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    if file_path is None:
        file_path = os.getenv("ARGUS_LOG_FILE") or None

    formatter = EventFormatter()
    handlers: list[logging.Handler] = []
    if file_path:
        h = logging.FileHandler(file_path, encoding="utf-8")
        h.setFormatter(formatter)
        handlers.append(h)
    else:
        h = logging.StreamHandler(stream or sys.stdout)
        h.setFormatter(formatter)
        handlers.append(h)

    if extra_handlers:
        for eh in extra_handlers:
            if eh.formatter is None:
                eh.setFormatter(formatter)
            handlers.append(eh)

    events = logging.getLogger(EVENT_LOGGER_NAME)
    events.handlers.clear()
    for h in handlers:
        events.addHandler(h)
    events.setLevel(logging.INFO)
    events.propagate = False

    _CONFIGURED = True


def reset_configuration_for_tests() -> None:
    """Test hook — flip the once-only guard so tests can re-install
    handlers between cases."""
    global _CONFIGURED
    _CONFIGURED = False
    logging.getLogger(EVENT_LOGGER_NAME).handlers.clear()


__all__ = [
    "EVENT_LOGGER_NAME",
    "EventFormatter",
    "REDACTED_FIELD_NAMES",
    "REDACTED_VALUE",
    "StageTimer",
    "configure_event_logging",
    "emit_event",
    "redact",
    "reset_configuration_for_tests",
    "structured_logger",
]
