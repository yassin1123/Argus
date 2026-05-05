"""Schema-repair prompts for JSON structured generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import ValidationError


def schema_excerpt(model_cls: type, max_len: int = 6000) -> str:
    return json.dumps(model_cls.model_json_schema(), ensure_ascii=False)[:max_len]


def build_schema_repair_message(schema_hint: str, ve: ValidationError, max_total: int = 8000) -> str:
    return (
        "Your previous JSON failed validation. Output JSON matching the expected shape.\n"
        f"Schema excerpt:\n{schema_hint[:3500]}\nPydantic errors:\n{ve!s}"
    )[:max_total]
