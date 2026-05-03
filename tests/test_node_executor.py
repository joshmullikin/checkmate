from unittest.mock import AsyncMock

import pytest

from agent.nodes.executor import execute_step


@pytest.mark.asyncio
async def test_execute_step_returns_current_when_no_plan():
    result = await execute_step({"current_step": 2})
    assert result == {"current_step": 2}


@pytest.mark.asyncio
async def test_execute_step_updates_results_and_browser_state_for_navigate():
    state = {
        "current_step": 0,
        "test_plan": {
            "steps": [
                {
                    "action": "navigate",
                    "value": "https://example.com/login",
                    "description": "Go to login",
                }
            ]
        },
        "test_results": [],
        "browser_state": {},
    }

    result = await execute_step(state)

    assert result["current_step"] == 1
    assert len(result["test_results"]) == 1
    assert result["test_results"][0]["status"] == "passed"
    assert result["browser_state"]["current_url"] == "https://example.com/login"


@pytest.mark.asyncio
async def test_execute_step_marks_failed_when_sleep_errors(monkeypatch):
    monkeypatch.setattr("agent.nodes.executor.asyncio.sleep", AsyncMock(side_effect=RuntimeError("boom")))

    state = {
        "current_step": 0,
        "test_plan": {"steps": [{"action": "click", "target": "Sign in", "description": "Click"}]},
        "test_results": [],
        "browser_state": {},
    }

    result = await execute_step(state)
    assert result["test_results"][0]["status"] == "failed"
    assert "boom" in result["test_results"][0]["error"]