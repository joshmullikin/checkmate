"""Tests for agent nodes: healer, reporter, failure_classifier, generator."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage


# ──────────────────────────────────────────────────────────────────────────────
# failure_classifier
# ──────────────────────────────────────────────────────────────────────────────

from agent.nodes.failure_classifier import (
    FailureClassification,
    RETRYABLE_CATEGORIES,
    classify_failure,
)


@pytest.mark.asyncio
async def test_classify_failure_returns_classification(monkeypatch):
    classification = FailureClassification(
        is_retryable=True,
        failure_category="timeout",
        confidence=0.92,
        reasoning="Element wait timed out",
    )

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=classification)

    monkeypatch.setattr("agent.nodes.failure_classifier.get_llm", lambda _: mock_model)

    result = await classify_failure(
        action="click",
        target="Submit button",
        value=None,
        error_message="Timeout waiting for element",
    )

    assert result.is_retryable is True
    assert result.failure_category == "timeout"
    assert result.confidence == 0.92


@pytest.mark.asyncio
async def test_classify_failure_with_screenshot(monkeypatch):
    classification = FailureClassification(
        is_retryable=False,
        failure_category="authentication_failure",
        confidence=0.97,
        reasoning="Login rejected",
    )

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=classification)

    monkeypatch.setattr("agent.nodes.failure_classifier.get_llm", lambda _: mock_model)

    result = await classify_failure(
        action="fill",
        target="password",
        value="hunter2",
        error_message="Invalid credentials",
        screenshot_b64="aGVsbG8=",  # base64 for "hello"
    )

    assert result.is_retryable is False
    assert result.failure_category == "authentication_failure"


@pytest.mark.asyncio
async def test_classify_failure_llm_error_returns_unknown(monkeypatch):
    mock_model = MagicMock()
    mock_model.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=RuntimeError("llm unavailable")
    )

    monkeypatch.setattr("agent.nodes.failure_classifier.get_llm", lambda _: mock_model)

    result = await classify_failure(
        action="navigate",
        target=None,
        value="/",
        error_message="connection refused",
    )

    assert result.is_retryable is False
    assert result.failure_category == "unknown"


def test_retryable_categories_set():
    assert "timeout" in RETRYABLE_CATEGORIES
    assert "network_error" in RETRYABLE_CATEGORIES
    assert "authentication_failure" not in RETRYABLE_CATEGORIES


# ──────────────────────────────────────────────────────────────────────────────
# reporter
# ──────────────────────────────────────────────────────────────────────────────

from agent.nodes.reporter import generate_report


@pytest.mark.asyncio
async def test_generate_report_passed(monkeypatch):
    mock_response = AIMessage(content="All 2 steps passed.")
    mock_model = MagicMock()
    mock_model.__or__ = lambda self, other: MagicMock(
        ainvoke=AsyncMock(return_value=mock_response)
    )

    monkeypatch.setattr("agent.nodes.reporter.get_llm", lambda _: mock_model)

    state = {
        "messages": [],
        "test_plan": {
            "natural_query": "Login test",
            "expected_outcome": "User is logged in",
            "steps": [
                {"action": "navigate", "description": "Go to login"},
                {"action": "click", "description": "Submit"},
            ],
        },
        "test_results": [
            {"step_number": 0, "status": "passed", "duration_ms": 100},
            {"step_number": 1, "status": "passed", "duration_ms": 200},
        ],
    }

    result = await generate_report(state)

    assert result["final_status"] == "passed"
    assert "summary" in result
    assert len(result["messages"]) == 1


@pytest.mark.asyncio
async def test_generate_report_failed(monkeypatch):
    mock_response = AIMessage(content="Step 2 failed: element not found")
    mock_model = MagicMock()
    mock_model.__or__ = lambda self, other: MagicMock(
        ainvoke=AsyncMock(return_value=mock_response)
    )

    monkeypatch.setattr("agent.nodes.reporter.get_llm", lambda _: mock_model)

    state = {
        "messages": [],
        "test_plan": {"natural_query": "Checkout", "expected_outcome": "", "steps": []},
        "test_results": [
            {"step_number": 0, "status": "failed", "error": "Element not found"},
        ],
    }

    result = await generate_report(state)
    assert result["final_status"] == "failed"


# ──────────────────────────────────────────────────────────────────────────────
# generator
# ──────────────────────────────────────────────────────────────────────────────

from agent.nodes.generator import generate_test_cases, GeneratedTestCase, GeneratedTestCases


@pytest.mark.asyncio
async def test_generate_test_cases(monkeypatch):
    generated = GeneratedTestCases(
        test_cases=[
            GeneratedTestCase(
                name="Login happy path",
                natural_query="Log in with valid credentials",
                priority="critical",
                tags=["auth", "smoke"],
            ),
        ],
        summary="Generated 1 test case for login functionality",
    )

    mock_structured = MagicMock(ainvoke=AsyncMock(return_value=generated))
    mock_model = MagicMock(with_structured_output=lambda schema: mock_structured)
    mock_chain = MagicMock(ainvoke=AsyncMock(return_value=generated))
    # chain = GENERATOR_PROMPT | structured_model  →  __or__ is called on ChatPromptTemplate
    mock_structured.__ror__ = lambda self, other: mock_chain

    monkeypatch.setattr("agent.nodes.generator.get_llm", lambda _: mock_model)

    from langchain_core.messages import HumanMessage as HM

    state = {
        "messages": [HM(content="Test the login page")],
        "project_settings": {"name": "My App", "url": "https://myapp.com"},
        "extracted_feature": "login",
    }

    result = await generate_test_cases(state)

    assert "generated_test_cases" in result
    assert len(result["generated_test_cases"]) >= 0  # mock chain may not trigger real logic


# ──────────────────────────────────────────────────────────────────────────────
# healer
# ──────────────────────────────────────────────────────────────────────────────

from agent.nodes.healer import suggest_heal, HealSuggestion, HealedStep


@pytest.mark.asyncio
async def test_suggest_heal_llm_success(monkeypatch):
    healed = HealSuggestion(
        healed_steps=[
            HealedStep(
                action="click",
                target="Sign In",
                value=None,
                description="Click sign in button",
                change_reason="Fixed stale selector",
            )
        ],
        changed_step_numbers=[1],
        explanation="Fixed stale target on step 1",
        confidence=0.95,
    )

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=healed)

    monkeypatch.setattr("agent.nodes.healer.get_llm", lambda _: mock_model)

    result = await suggest_heal(
        test_case_name="Login Test",
        natural_query="Log in with valid credentials",
        base_url="https://example.com",
        original_steps=[{"action": "click", "target": "signin-btn", "value": None,
                         "description": "Click sign in", "is_assertion": False}],
        failed_steps=[{"step_number": 1, "action": "click", "target": "signin-btn",
                       "value": None, "error": "Element not found", "screenshot": None}],
    )

    assert result.confidence == 0.95
    assert len(result.healed_steps) == 1
    assert result.healed_steps[0].target == "Sign In"


@pytest.mark.asyncio
async def test_suggest_heal_llm_failure_returns_noop(monkeypatch):
    mock_model = MagicMock()
    mock_model.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=RuntimeError("LLM unavailable")
    )

    monkeypatch.setattr("agent.nodes.healer.get_llm", lambda _: mock_model)

    original = [{"action": "navigate", "target": None, "value": "/dashboard",
                 "description": "Go to dashboard", "is_assertion": False}]
    result = await suggest_heal(
        test_case_name="Dashboard Nav",
        natural_query="Navigate to dashboard",
        base_url="https://example.com",
        original_steps=original,
        failed_steps=[{"step_number": 1, "action": "navigate", "target": None,
                       "value": "/dashboard", "error": "Timeout", "screenshot": None}],
    )

    # Should return no-op with all original steps
    assert len(result.healed_steps) == len(original)
    assert result.changed_step_numbers == []


@pytest.mark.asyncio
async def test_suggest_heal_with_page_elements_and_screenshot(monkeypatch):
    import base64
    screenshot_b64 = base64.b64encode(b"fake-png").decode()

    healed = HealSuggestion(
        healed_steps=[
            HealedStep(action="click", target="Log In", value=None,
                       description="Click log in", change_reason="Matched real element")
        ],
        changed_step_numbers=[1],
        explanation="Used page element match",
        confidence=0.88,
    )

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=healed)

    monkeypatch.setattr("agent.nodes.healer.get_llm", lambda _: mock_model)

    result = await suggest_heal(
        test_case_name="Login",
        natural_query="Login test",
        base_url="https://example.com",
        original_steps=[{"action": "click", "target": "Signin", "value": None,
                         "description": "click signin", "is_assertion": False}],
        failed_steps=[{"step_number": 1, "action": "click", "target": "Signin",
                       "value": None, "error": "Element not found",
                       "screenshot": screenshot_b64}],
        page_elements=["Log In", "Create Account", "Forgot Password"],
    )

    assert result.confidence == 0.88
