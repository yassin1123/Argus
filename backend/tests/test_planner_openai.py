import os

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
async def test_planner_output_structure() -> None:
    from agents.planner import PlannerAgent

    planner = PlannerAgent()
    result = await planner.run(
        query="Should a startup expand into Germany or France first?",
        context="",
    )
    assert "objective" in result
    assert "tasks" in result
    assert isinstance(result["tasks"], list)
    assert len(result["tasks"]) >= 3
    for task in result["tasks"]:
        assert "question" in task
        assert "priority" in task
