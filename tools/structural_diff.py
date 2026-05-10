"""Phase 2 / Week 7 / Day 4 — structural diff for two writer-payload JSONs.

Pure-Python utility. No LLM calls. Used by the Day 5 e2e wrap-up
to summarise how two engagement runs differ in shape — which
top-level fields are present in each, which fields differ in
shape (string vs list vs dict), and which leaf scalars carry
different values.

Output is either plain text (default, for inclusion in the
wrap-up doc) or JSON (--json, for tooling).

Usage::

    python tools/structural_diff.py A.json B.json
    python tools/structural_diff.py --json A.json B.json > diff.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _shape(v: Any) -> str:
    """Coarse type label for shape comparison."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        if not v:
            return "list[empty]"
        # Take the first item's shape as the row shape.
        return f"list[{_shape(v[0])}]"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__


def _walk(payload: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a JSON payload into ``{dotted_path: value}`` for
    comparable scalar lookups. Lists are not exploded — a list field
    is a single entry whose value is the list itself (we only
    diff shapes for lists, not contents).
    """
    out: dict[str, Any] = {}
    if isinstance(payload, dict):
        for k, v in payload.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_walk(v, path))
            else:
                out[path] = v
    else:
        out[prefix or "(root)"] = payload
    return out


def structural_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Diff two top-level dicts.

    Returns::

        {
          "only_in_a": [path],
          "only_in_b": [path],
          "shape_changes": [{path, a_shape, b_shape}],
          "scalar_changes": [{path, a_value, b_value}],
          "matched": [path],
        }
    """
    flat_a = _walk(a)
    flat_b = _walk(b)
    keys_a = set(flat_a.keys())
    keys_b = set(flat_b.keys())

    only_in_a = sorted(keys_a - keys_b)
    only_in_b = sorted(keys_b - keys_a)

    shape_changes: list[dict[str, str]] = []
    scalar_changes: list[dict[str, Any]] = []
    matched: list[str] = []

    for k in sorted(keys_a & keys_b):
        va, vb = flat_a[k], flat_b[k]
        sa, sb = _shape(va), _shape(vb)
        if sa != sb:
            shape_changes.append({"path": k, "a_shape": sa, "b_shape": sb})
            continue
        # Same shape — compare value if scalar; for lists, just count.
        if isinstance(va, (str, int, float, bool)) or va is None:
            if va != vb:
                scalar_changes.append({"path": k, "a_value": va, "b_value": vb})
            else:
                matched.append(k)
        elif isinstance(va, list):
            if len(va) != len(vb):
                shape_changes.append(
                    {
                        "path": k,
                        "a_shape": f"list[len={len(va)}]",
                        "b_shape": f"list[len={len(vb)}]",
                    }
                )
            else:
                matched.append(k)
        else:
            matched.append(k)

    return {
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "shape_changes": shape_changes,
        "scalar_changes": scalar_changes,
        "matched": matched,
    }


def render_text(diff: dict[str, Any], a_label: str, b_label: str) -> str:
    """Pretty-print a structural diff for inclusion in a wrap-up doc."""
    lines: list[str] = []
    lines.append(f"# Structural diff: {a_label} vs {b_label}")
    lines.append("")
    lines.append(f"Matched fields:        {len(diff['matched'])}")
    lines.append(f"Only in {a_label}:     {len(diff['only_in_a'])}")
    lines.append(f"Only in {b_label}:     {len(diff['only_in_b'])}")
    lines.append(f"Shape changes:         {len(diff['shape_changes'])}")
    lines.append(f"Scalar value changes:  {len(diff['scalar_changes'])}")
    lines.append("")

    if diff["only_in_a"]:
        lines.append(f"## Only in {a_label}")
        for k in diff["only_in_a"]:
            lines.append(f"  - {k}")
        lines.append("")
    if diff["only_in_b"]:
        lines.append(f"## Only in {b_label}")
        for k in diff["only_in_b"]:
            lines.append(f"  - {k}")
        lines.append("")
    if diff["shape_changes"]:
        lines.append("## Shape changes")
        for s in diff["shape_changes"]:
            lines.append(f"  - {s['path']}: {s['a_shape']} -> {s['b_shape']}")
        lines.append("")
    if diff["scalar_changes"]:
        lines.append("## Scalar value changes")
        for s in diff["scalar_changes"]:
            av = repr(s["a_value"])[:80]
            bv = repr(s["b_value"])[:80]
            lines.append(f"  - {s['path']}: {av} -> {bv}")

    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("a", help="Path to first JSON file (or '-' for stdin).")
    p.add_argument("b", help="Path to second JSON file.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    p.add_argument("--label-a", default=None, help="Label for the first file in text output.")
    p.add_argument("--label-b", default=None, help="Label for the second file in text output.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    a_text = sys.stdin.read() if args.a == "-" else open(args.a, encoding="utf-8").read()
    b_text = open(args.b, encoding="utf-8").read()
    a_data = json.loads(a_text)
    b_data = json.loads(b_text)
    if not isinstance(a_data, dict) or not isinstance(b_data, dict):
        print("error: both inputs must be JSON objects (dicts)", file=sys.stderr)
        sys.exit(2)
    diff = structural_diff(a_data, b_data)
    if args.json:
        json.dump(diff, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        a_label = args.label_a or args.a
        b_label = args.label_b or args.b
        print(render_text(diff, a_label, b_label))


if __name__ == "__main__":
    main()
