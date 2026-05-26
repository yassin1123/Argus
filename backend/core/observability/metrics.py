"""Metrics collection — Phase 5 / Week 20 / Day 2.

Lightweight counter / gauge / histogram primitives backed by the
``metric_events`` table (migration 045). Pilot-scale volume —
low-hundreds of engagements/day — is comfortably served by raw
event rows; rollup tables can land later if the query layer
starts feeling pressure.

Two surfaces:

  - :func:`increment` — bump a counter by ``value`` (default 1)
  - :func:`observe` — record a histogram sample (latency,
    payload bytes, token count). Stored as one row per sample;
    aggregation happens in the query API.

Both are best-effort. A DB write failure during metrics emission
**never** raises — the pipeline must not be coupled to the
metrics sink. ``logger.debug`` records the drop so an operator
investigating "where are my numbers" can find the cause.

Privacy invariant (matches the W20/D1 redact rule): labels carry
**IDs + enums + counts** only — never claim text, evidence
content, memo prose, free-form user input. The label-shape
sanitiser :func:`_clean_labels` enforces this by accepting only
safe scalar types and a hard length cap on string values.

The trace_id + firm_id are pulled automatically from the W20/D1
:mod:`trace` context so call-sites don't have to thread them
through; promoting them to top-level columns keeps the firm-
scoping index cheap.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator
from uuid import UUID

from db.connection import acquire

from .trace import get_trace_context

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label sanitiser
# ---------------------------------------------------------------------------


# Maximum length of any string label value. Generous enough for
# error_type strings ("WriterSchemaValidationError") + tight enough
# that nobody can sneak prose into a label.
_LABEL_VALUE_MAX = 128


def _clean_labels(labels: dict[str, Any] | None) -> dict[str, Any]:
    """Reject non-scalar values + cap string length. Keeps the
    label surface a fixed-cardinality enum, not a free-form bag.

    Accepted types: ``str``, ``int``, ``float``, ``bool``. Strings
    over the cap are truncated. ``None`` keys / values are dropped.
    Anything else (lists, dicts, complex objects) is dropped and
    logged at DEBUG.
    """
    if not labels:
        return {}
    out: dict[str, Any] = {}
    for k, v in labels.items():
        if not isinstance(k, str) or not k:
            continue
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = v
            continue
        if isinstance(v, (int, float)):
            out[k] = v
            continue
        if isinstance(v, str):
            out[k] = v[:_LABEL_VALUE_MAX]
            continue
        # UUIDs, enums (.value attr) — coerce to str then cap.
        if isinstance(v, UUID):
            out[k] = str(v)
            continue
        val = getattr(v, "value", None)
        if isinstance(val, (str, int, float)):
            out[k] = val if not isinstance(val, str) else val[:_LABEL_VALUE_MAX]
            continue
        logger.debug("metrics: dropped non-scalar label %s=%r", k, type(v))
    return out


def _coerce_uuid(value: Any) -> str | None:
    """Best-effort UUID-shape coerce for the top-level columns.
    Returns ``None`` on anything that doesn't look like a UUID so
    we never try to insert a bogus value into the typed column."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    s = str(value)
    if len(s) == 36 and s.count("-") == 4:
        return s
    return None


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


async def _persist(metric_name: str, value: float, labels: dict[str, Any]) -> None:
    """Insert one row into ``metric_events``. Best-effort — every
    failure mode is swallowed + logged at DEBUG so a metrics
    outage cannot fail a pipeline run."""
    ctx = get_trace_context()
    trace_id = _coerce_uuid(ctx.trace_id)
    # firm_id lives in two places: an explicit label (preferred,
    # call-site sets it) or the trace context (when the pipeline
    # binding seeded it). Label wins so a single call can override
    # for things like firm-admin cross-firm queries.
    firm_id = _coerce_uuid(labels.get("firm_id") or ctx.firm_id)
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO metric_events
                    (metric_name, labels, value, trace_id, firm_id)
                VALUES ($1, $2::jsonb, $3, $4::uuid, $5::uuid)
                """,
                metric_name,
                json.dumps(labels),
                float(value),
                trace_id,
                firm_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("metric write skipped: %s name=%s", e, metric_name)


# ---------------------------------------------------------------------------
# Public API — increment / observe
# ---------------------------------------------------------------------------


async def increment(
    metric_name: str,
    labels: dict[str, Any] | None = None,
    *,
    value: float = 1.0,
) -> None:
    """Bump the counter named ``metric_name`` by ``value``.

    Use for event counts: engagements started, LLM calls, errors,
    artifacts generated. The query layer sums values over a window.
    """
    await _persist(metric_name, float(value), _clean_labels(labels))


async def observe(
    metric_name: str,
    value: float,
    labels: dict[str, Any] | None = None,
) -> None:
    """Record one histogram/gauge sample.

    Use for latencies (``llm.latency_ms``, ``pipeline.stage_latency_ms``),
    sizes (``llm.tokens``, ``writer.payload_bytes``), and gauges
    that read the current value of something. The query layer
    aggregates samples (count/avg/p50/p95/p99) over a window.
    """
    await _persist(metric_name, float(value), _clean_labels(labels))


@contextmanager
def time_observe(
    metric_name: str,
    labels: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Sync helper — time a ``with`` block, schedule an observe
    on exit. Useful for tight CPU work. For async work prefer the
    ``async with`` analogue below."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        # Fire-and-forget — schedule the write without awaiting.
        # The caller is sync; we use ``asyncio.create_task`` only
        # when an event loop is running, otherwise drop.
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(observe(metric_name, ms, labels))


# ---------------------------------------------------------------------------
# Stage-latency convenience helpers
# ---------------------------------------------------------------------------


async def record_stage_latency(
    stage: str, duration_ms: float, /,
    *, outcome: str = "ok", **extra_labels: Any,
) -> None:
    """Record one ``pipeline.stage_latency_ms`` sample.

    Convenience over ``observe`` — the orchestrator already
    measures durations for the W20/D1 structured logs; this
    feeds the same numbers into the metrics store with the
    canonical label shape.
    """
    labels: dict[str, Any] = {"stage": stage, "outcome": outcome}
    labels.update(extra_labels)
    await observe("pipeline.stage_latency_ms", duration_ms, labels)


async def record_error(
    stage: str, error_type: str, /,
    **extra_labels: Any,
) -> None:
    """Bump ``error.count`` labelled by stage + error_type.
    Pipeline failure paths call this so the error-rate dashboard
    can break down what's breaking and where."""
    labels: dict[str, Any] = {"stage": stage, "error_type": error_type}
    labels.update(extra_labels)
    await increment("error.count", labels)


# ---------------------------------------------------------------------------
# Read path — query helpers used by the metrics API
# ---------------------------------------------------------------------------


async def query_window(
    metric_name: str,
    *,
    from_ts: Any | None = None,
    to_ts: Any | None = None,
    firm_id: str | None = None,
    group_by: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Aggregate ``metric_events`` rows for ``metric_name`` over a
    time window, optionally grouped by one label dimension.

    Returns a list of ``{"group": <value>, "count": int,
    "sum": float, "avg": float, "min": float, "max": float}``
    rows. When ``group_by`` is ``None`` a single all-up row is
    returned (the caller's "totals" view).

    Firm scoping is the caller's responsibility — pass
    ``firm_id`` for a firm_admin's request; omit for system-admin
    cross-firm queries. The metrics API enforces the auth rule;
    this layer just executes the filter.
    """
    clauses = ["metric_name = $1"]
    params: list[Any] = [metric_name]
    if from_ts is not None:
        params.append(from_ts)
        clauses.append(f"recorded_at >= ${len(params)}")
    if to_ts is not None:
        params.append(to_ts)
        clauses.append(f"recorded_at < ${len(params)}")
    if firm_id is not None:
        params.append(firm_id)
        clauses.append(f"firm_id = ${len(params)}::uuid")
    where = " AND ".join(clauses)

    if group_by:
        # Group by one JSONB label field. JSON path is parameterised
        # to avoid string-concat injection.
        params.append(group_by)
        group_expr = f"labels ->> ${len(params)}"
        sql = (
            f"SELECT {group_expr} AS grp, "
            "COUNT(*) AS count, SUM(value) AS sum, AVG(value) AS avg, "
            "MIN(value) AS min, MAX(value) AS max "
            f"FROM metric_events WHERE {where} "
            f"GROUP BY {group_expr} "
            f"ORDER BY count DESC LIMIT {int(limit)}"
        )
    else:
        sql = (
            "SELECT NULL AS grp, COUNT(*) AS count, SUM(value) AS sum, "
            "AVG(value) AS avg, MIN(value) AS min, MAX(value) AS max "
            f"FROM metric_events WHERE {where}"
        )

    try:
        async with acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception as e:  # noqa: BLE001
        logger.debug("metric query failed: %s", e)
        return []
    return [
        {
            "group": r["grp"],
            "count": int(r["count"] or 0),
            "sum": float(r["sum"] or 0.0),
            "avg": float(r["avg"] or 0.0),
            "min": float(r["min"] or 0.0),
            "max": float(r["max"] or 0.0),
        }
        for r in rows
    ]


async def list_metric_names(firm_id: str | None = None) -> list[str]:
    """Return the set of metric_name values present, optionally
    firm-scoped. Used by the Prometheus export to enumerate what
    to render."""
    clauses: list[str] = []
    params: list[Any] = []
    if firm_id is not None:
        params.append(firm_id)
        clauses.append(f"firm_id = ${len(params)}::uuid")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT DISTINCT metric_name FROM metric_events{where} ORDER BY metric_name"
    try:
        async with acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception:  # noqa: BLE001
        return []
    return [r["metric_name"] for r in rows]


# ---------------------------------------------------------------------------
# Prometheus text-format export
# ---------------------------------------------------------------------------


_PROM_NAME_TRANSLATE = str.maketrans({".": "_", "-": "_"})


def _prom_metric_name(name: str) -> str:
    """Translate dot-notation metric names to Prometheus's
    ``snake_case`` convention. ``llm.call`` → ``llm_call``."""
    return name.translate(_PROM_NAME_TRANSLATE)


def _prom_escape_label_value(s: str) -> str:
    """Escape backslash, double-quote, newline per the Prometheus
    exposition format spec."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_prom_labels(group: dict[str, str] | None) -> str:
    if not group:
        return ""
    parts = [
        f'{k}="{_prom_escape_label_value(str(v))}"'
        for k, v in group.items() if v is not None
    ]
    return "{" + ",".join(parts) + "}" if parts else ""


async def render_prometheus(firm_id: str | None = None) -> str:
    """Render all current metrics as a Prometheus exposition-format
    string. Counters → ``_total`` suffix + sum; histograms →
    ``_count`` + ``_sum`` + ``_avg`` (lightweight summary, not the
    full bucketed histogram — that's a Phase 5 W22 polish item).

    Output is grouped by metric, sorted, with a HELP/TYPE line per
    metric. Designed to be scraped at low frequency (15-60s)
    without putting load on the table.
    """
    names = await list_metric_names(firm_id=firm_id)
    out: list[str] = []
    for name in names:
        rows = await query_window(
            name, firm_id=firm_id, group_by=None, limit=1,
        )
        if not rows:
            continue
        prom = _prom_metric_name(name)
        is_histogram = any(
            tok in name for tok in (".latency_ms", ".tokens", ".bytes", ".duration")
        )
        if is_histogram:
            out.append(f"# HELP {prom} histogram-style metric")
            out.append(f"# TYPE {prom} summary")
            r = rows[0]
            out.append(f"{prom}_count {r['count']}")
            out.append(f"{prom}_sum {r['sum']}")
            out.append(f"{prom}_avg {r['avg']}")
        else:
            out.append(f"# HELP {prom} counter")
            out.append(f"# TYPE {prom} counter")
            r = rows[0]
            out.append(f"{prom}_total {r['sum']}")
    return "\n".join(out) + ("\n" if out else "")


__all__ = [
    "increment",
    "list_metric_names",
    "observe",
    "query_window",
    "record_error",
    "record_stage_latency",
    "render_prometheus",
    "time_observe",
]
