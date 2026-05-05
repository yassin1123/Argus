import json
import re


def parse_llm_json(text: str) -> dict:
    """Extract and parse JSON from LLM output (handles optional markdown fences)."""
    s = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", s)
    if fence:
        s = fence.group(1).strip()
    return json.loads(s)
