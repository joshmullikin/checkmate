"""Integration tests for api/routes/agent.py"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _make_project(client, name="Agent Project"):
    res = client.post(
        "/api/projects",
        json={
            "name": name,
            "description": "",
            "base_url": "https://example.com",
            "config": "{}",
            "base_prompt": "Base prompt",
            "page_load_state": "load",
        },
    )
    assert res.status_code == 200
    return res.json()["id"]


@pytest.mark.asyncio
async def test_build_project_not_found(client):
    res = client.post("/api/agent/projects/999999/build", json={"message": "build login test"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_build_builder_error(client, monkeypatch):
    pid = _make_project(client)

    async def boom(**kwargs):
        raise RuntimeError("builder exploded")

    monkeypatch.setattr("api.routes.agent.build_test_case", boom)

    res = client.post(f"/api/agent/projects/{pid}/build", json={"message": "build test"})
    assert res.status_code == 500
    assert "Builder error" in res.json()["detail"]


@pytest.mark.asyncio
async def test_build_success_with_current_test_case(client, monkeypatch):
    pid = _make_project(client)

    fake_result = SimpleNamespace(
        test_case=SimpleNamespace(
            name="Login happy path",
            natural_query="test login",
            priority="high",
            tags=["auth"],
            steps=[SimpleNamespace(action="navigate", target=None, value="/login", description="Go login")],
            fixture_ids=[1, 2],
        ),
        message="Updated test",
        needs_clarification=False,
    )

    monkeypatch.setattr("api.routes.agent.build_test_case", AsyncMock(return_value=fake_result))

    res = client.post(
        f"/api/agent/projects/{pid}/build",
        json={
            "message": "add a submit click",
            "previous_messages": ["create login test"],
            "test_case": {
                "name": "Login",
                "natural_query": "test login",
                "priority": "medium",
                "tags": ["auth"],
                "steps": [
                    {"action": "navigate", "target": None, "value": "/login", "description": "Go"}
                ],
                "original_steps": [
                    {"action": "navigate", "target": None, "value": "/login", "description": "Go"}
                ],
            },
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert data["test_case"]["name"] == "Login happy path"
    assert data["test_case"]["fixture_ids"] == [1, 2]
    assert data["needs_clarification"] is False


@pytest.mark.asyncio
async def test_chat_project_not_found(client):
    res = client.post("/api/agent/projects/999999/chat", json={"message": "run login"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_chat_graph_error(client, monkeypatch):
    pid = _make_project(client)

    async def boom(*args, **kwargs):
        raise RuntimeError("graph failed")

    monkeypatch.setattr("api.routes.agent.graph.ainvoke", boom)

    res = client.post(f"/api/agent/projects/{pid}/chat", json={"message": "run login"})
    assert res.status_code == 500
    assert "Agent error" in res.json()["detail"]


@pytest.mark.asyncio
async def test_chat_success_and_saves_generated_test_cases(client, monkeypatch):
    pid = _make_project(client)

    fake_response = {
        "messages": [SimpleNamespace(content="Generated tests")],
        "intent": "generate_test_cases",
        "summary": "done",
        "generated_test_cases": [
            {"name": "Login", "natural_query": "login flow", "priority": "medium", "tags": ["auth"]},
            {"name": "Checkout", "natural_query": "checkout flow", "priority": "high", "tags": ["checkout"]},
        ],
    }

    monkeypatch.setattr("api.routes.agent.graph.ainvoke", AsyncMock(return_value=fake_response))

    res = client.post(f"/api/agent/projects/{pid}/chat", json={"message": "generate tests"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "generate_test_cases"
    assert data["summary"] == "done"
    assert len(data["generated_test_cases"]) == 2


@pytest.mark.asyncio
async def test_chat_success_without_generated_cases(client, monkeypatch):
    pid = _make_project(client)

    fake_response = {
        "messages": [SimpleNamespace(content="No generation")],
        "intent": "execute_test",
        "test_plan": {"steps": []},
        "generated_test_cases": [],
    }

    monkeypatch.setattr("api.routes.agent.graph.ainvoke", AsyncMock(return_value=fake_response))

    res = client.post(
        f"/api/agent/projects/{pid}/chat",
        json={"message": "run login", "thread_id": "thread-123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["thread_id"] == "thread-123"
    assert data["generated_test_cases"] is None
    assert data["message"] == "No generation"
