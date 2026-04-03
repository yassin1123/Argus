import json
import pathlib


def test_golden_tasks_extended_schema() -> None:
    p = pathlib.Path(__file__).parent / "fixtures" / "golden_tasks.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data.get("version") == 2
    tasks = data.get("tasks") or []
    assert len(tasks) >= 3
    for t in tasks:
        assert isinstance(t.get("id"), str)
        assert isinstance(t.get("description"), str)
        assert isinstance(t.get("rubric"), list)
