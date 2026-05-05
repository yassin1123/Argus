import json
from io import BytesIO
from typing import Any

import pandas as pd


def parse_csv(file_bytes: bytes) -> dict[str, Any]:
    df = pd.read_csv(BytesIO(file_bytes))
    summary = f"Columns: {list(df.columns)}\n"
    summary += f"Rows: {len(df)}\n"
    summary += f"Data types: {df.dtypes.to_dict()}\n\n"
    summary += "Statistical summary:\n"
    summary += df.describe().to_string()
    summary += "\n\nFirst 20 rows:\n"
    summary += df.head(20).to_string()
    return {
        "content": summary,
        "columns": list(df.columns),
        "row_count": len(df),
        "column_count": len(df.columns),
    }


def parse_json(file_bytes: bytes) -> dict[str, Any]:
    data = json.loads(file_bytes.decode("utf-8", errors="replace"))
    formatted = json.dumps(data, indent=2)
    keys: Any
    if isinstance(data, dict):
        keys = list(data.keys())
    else:
        keys = "array"
    return {
        "content": formatted,
        "keys": keys,
        "size": len(formatted),
    }
