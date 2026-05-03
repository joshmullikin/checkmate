"""Tests for agent/nodes/classifier.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from agent.nodes.classifier import classify_intent, IntentClassification


def _make_mock_model(classification):
    """Return a mock get_llm result whose structured_output runnable returns classification."""
    async def _return_classification(_input):
        return classification

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = RunnableLambda(_return_classification)
    return mock_model


@pytest.mark.asyncio
async def test_classify_intent_execute_test(monkeypatch):
    classification = IntentClassification(
        intent="execute_test",
        confidence=0.95,
        extracted_feature="login",
    )

    monkeypatch.setattr("agent.nodes.classifier.get_llm", lambda _: _make_mock_model(classification))

    state = {
        "messages": [HumanMessage(content="Is login working?")],
        "project_settings": {"name": "My App", "url": "https://myapp.com"},
    }

    result = await classify_intent(state)

    assert result["intent"] == "execute_test"
    assert result["confidence"] == 0.95
    assert result["extracted_feature"] == "login"


@pytest.mark.asyncio
async def test_classify_intent_generate_test_cases(monkeypatch):
    classification = IntentClassification(
        intent="generate_test_cases",
        confidence=0.88,
        extracted_feature="checkout",
    )

    monkeypatch.setattr("agent.nodes.classifier.get_llm", lambda _: _make_mock_model(classification))

    state = {
        "messages": [HumanMessage(content="Generate tests for the checkout flow")],
        "project_settings": None,
        "project_name": "Shop",
        "project_url": "https://shop.example.com",
    }

    result = await classify_intent(state)

    assert result["intent"] == "generate_test_cases"
    assert result["extracted_feature"] == "checkout"


@pytest.mark.asyncio
async def test_classify_intent_empty_messages(monkeypatch):
    classification = IntentClassification(
        intent="manage_project",
        confidence=0.5,
        extracted_feature=None,
    )

    monkeypatch.setattr("agent.nodes.classifier.get_llm", lambda _: _make_mock_model(classification))

    state = {"messages": []}

    result = await classify_intent(state)

    assert result["intent"] == "manage_project"
    assert result.get("extracted_feature") is None
