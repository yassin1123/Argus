import json

import pytest

from parsers.csv_parser import parse_csv, parse_json
from parsers.url_parser import validate_public_url


def test_csv_parser_extracts_columns() -> None:
    csv_data = b"name,value\nfoo,1\nbar,2"
    result = parse_csv(csv_data)
    assert "name" in result["columns"]
    assert result["row_count"] == 2


def test_json_parser() -> None:
    data = b'{"a": 1, "b": [1,2]}'
    result = parse_json(data)
    assert "a" in result["content"]


def test_validate_public_url_blocks_localhost() -> None:
    with pytest.raises(ValueError):
        validate_public_url("http://localhost/foo")


def test_validate_public_url_allows_https() -> None:
    assert validate_public_url("https://example.com/path").startswith("https://")
