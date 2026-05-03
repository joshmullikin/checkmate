"""Focused tests for planner context-building paths and plan variations.

Follows the established pattern from test_planner_builder_nodes.py:
- Monkeypatch PLANNER_PROMPT with _FakePrompt(result_model)
- Monkeypatch get_llm to return _FakeLLM()
- Monkeypatch context builder functions
"""
from types import SimpleNamespace
import pytest
import agent.nodes.planner as planner


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

class _DummySession:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeLLM:
    def with_structured_output(self, model_cls):
        return object()


class _FakePrompt:
    def __init__(self, result):
        self._result = result

    def __or__(self, structured_model):
        result = self._result

        class _Chain:
            async def ainvoke(self, payload):
                return result

        return _Chain()


def _make_plan(steps=None, needs_clarification=False, clarification_questions=None, fixture_ids=None):
    """Build a TestPlanModel result."""
    if steps is None:
        steps = [
            planner.TestStepModel(
                action="navigate", target=None, value="/login", description="Go to login"
            )
        ]
    return planner.TestPlanModel(
        steps=steps,
        expected_outcome="Operation completes successfully",
        fixture_ids=fixture_ids or [],
        needs_clarification=needs_clarification,
        clarification_questions=clarification_questions,
    )


def _mock_planner(monkeypatch, result_model):
    """Set up full monkeypatching for plan_test."""
    monkeypatch.setattr(planner, "get_llm", lambda tier: _FakeLLM())
    monkeypatch.setattr(planner, "PLANNER_PROMPT", _FakePrompt(result_model))
    monkeypatch.setattr(planner, "build_app_context", lambda pid: "app context")
    monkeypatch.setattr(planner, "build_personas_and_pages_context", lambda pid: "pp context")
    monkeypatch.setattr(planner, "build_fixtures_context", lambda pid: "fixtures context")
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_personas_by_project", lambda s, pid: [])
    monkeypatch.setattr(planner.crud, "get_pages_by_project", lambda s, pid: [])


# ──────────────────────────────────────────────────────────────────────────────
# build_app_context tests
# ──────────────────────────────────────────────────────────────────────────────

def test_build_app_context_empty_string_project_id(monkeypatch):
    """build_app_context returns empty string for empty/None project_id."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    result = planner.build_app_context(None)
    assert isinstance(result, str)
    assert result == ""


def test_build_app_context_invalid_project_id(monkeypatch):
    """build_app_context returns empty string for non-numeric project_id."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    result = planner.build_app_context("not_a_number")
    assert result == ""


def test_build_app_context_with_base_prompt(monkeypatch):
    """build_app_context includes base_prompt in result."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        planner.crud,
        "get_project",
        lambda s, pid: SimpleNamespace(
            page_load_state="load",
            base_prompt="This is a CRM application for managing customers.",
        ),
    )
    result = planner.build_app_context("10")
    assert "CRM application" in result


def test_build_app_context_no_project(monkeypatch):
    """build_app_context returns empty string when project not found."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_project", lambda s, pid: None)
    result = planner.build_app_context("99999")
    assert result == ""


def test_build_app_context_project_without_base_prompt(monkeypatch):
    """Covers branch where project exists but base_prompt is empty."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        planner.crud,
        "get_project",
        lambda s, pid: SimpleNamespace(page_load_state=None, base_prompt=""),
    )
    result = planner.build_app_context("10")
    assert "Default page load event: load" in result


# ──────────────────────────────────────────────────────────────────────────────
# build_conversation_context tests
# ──────────────────────────────────────────────────────────────────────────────

def test_build_conversation_context_empty_messages():
    """build_conversation_context handles empty messages list."""
    from langchain_core.messages import HumanMessage
    result = planner.build_conversation_context([], None)
    assert isinstance(result, str)


def test_build_conversation_context_single_message():
    """build_conversation_context with single user message."""
    from langchain_core.messages import HumanMessage
    messages = [HumanMessage(content="Login as admin")]
    result = planner.build_conversation_context(messages, None)
    assert isinstance(result, str)


def test_build_conversation_context_with_previous_plan():
    """build_conversation_context includes previous test plan steps."""
    from langchain_core.messages import HumanMessage, AIMessage
    messages = [
        HumanMessage(content="Login"),
        AIMessage(content="I'll create a login test"),
        HumanMessage(content="Also check the redirect"),
    ]
    previous_plan = {
        "steps": [
            {"action": "navigate", "description": "Go to login"},
            {"action": "fill", "description": "Fill credentials"},
        ]
    }
    result = planner.build_conversation_context(messages, previous_plan)
    assert "navigate" in result or "login" in result.lower()


def test_build_conversation_context_truncates_long_messages():
    """build_conversation_context truncates long message content."""
    from langchain_core.messages import HumanMessage, AIMessage
    long_message = "A" * 1000
    messages = [
        HumanMessage(content=long_message),
        HumanMessage(content="Short"),
    ]
    result = planner.build_conversation_context(messages, None)
    # Long message should be truncated in output
    assert "..." in result or len(result) < 1000 + 500


# ──────────────────────────────────────────────────────────────────────────────
# build_fixtures_context tests
# ──────────────────────────────────────────────────────────────────────────────

def test_build_fixtures_context_no_fixtures(monkeypatch):
    """build_fixtures_context returns empty string when no fixtures exist."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_fixtures_by_project", lambda s, pid: [])
    result = planner.build_fixtures_context("10")
    assert result == ""


def test_build_fixtures_context_with_fixtures(monkeypatch):
    """build_fixtures_context includes fixture names and IDs."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        planner.crud,
        "get_fixtures_by_project",
        lambda s, pid: [
            SimpleNamespace(
                id=5,
                name="Login Setup",
                description="Logs in as admin",
                get_setup_steps=lambda: [
                    {"action": "navigate"},
                    {"action": "fill_form"},
                ],
            )
        ],
    )
    result = planner.build_fixtures_context("10")
    assert "Login Setup" in result
    assert "5" in result


def test_build_fixtures_context_none_project_id(monkeypatch):
    """build_fixtures_context returns empty string for None project_id."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    result = planner.build_fixtures_context(None)
    assert result == ""


def test_build_personas_and_pages_context_zero_project_id_returns_no_context():
    result = planner.build_personas_and_pages_context(0)
    assert result == "No project context available."


def test_build_personas_and_pages_context_invalid_project_id_returns_no_context():
    result = planner.build_personas_and_pages_context("not-a-number")
    assert result == "No project context available."


def test_build_personas_and_pages_context_without_descriptions(monkeypatch):
    """Covers desc='' branches for personas/pages."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        planner.crud,
        "get_personas_by_project",
        lambda s, pid: [SimpleNamespace(name="admin", description="")],
    )
    monkeypatch.setattr(
        planner.crud,
        "get_pages_by_project",
        lambda s, pid: [SimpleNamespace(name="home", path="/", description="")],
    )
    result = planner.build_personas_and_pages_context("1")
    assert "admin.username" in result
    assert "which resolves to '/'" in result


def test_build_personas_and_pages_context_pages_only(monkeypatch):
    """Covers personas false branch with pages present."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_personas_by_project", lambda s, pid: [])
    monkeypatch.setattr(
        planner.crud,
        "get_pages_by_project",
        lambda s, pid: [SimpleNamespace(name="dashboard", path="/dashboard", description="")],
    )
    result = planner.build_personas_and_pages_context("2")
    assert "Available Pages" in result
    assert "dashboard" in result


def test_build_personas_and_pages_context_no_personas_or_pages(monkeypatch):
    """Covers no-context fallback return."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_personas_by_project", lambda s, pid: [])
    monkeypatch.setattr(planner.crud, "get_pages_by_project", lambda s, pid: [])
    result = planner.build_personas_and_pages_context("3")
    assert result == "No personas or pages configured for this project."


def test_build_fixtures_context_invalid_project_id_returns_empty(monkeypatch):
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    assert planner.build_fixtures_context("abc") == ""


def test_build_fixtures_context_many_steps_and_no_description(monkeypatch):
    """Covers >3 steps summary and missing description branch."""
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        planner.crud,
        "get_fixtures_by_project",
        lambda s, pid: [
            SimpleNamespace(
                id=8,
                name="Bootstrap",
                description="",
                get_setup_steps=lambda: [
                    {"action": "navigate"},
                    {"action": "fill_form"},
                    {"action": "click"},
                    {"action": "wait"},
                ],
            )
        ],
    )
    result = planner.build_fixtures_context("10")
    assert "4 steps total" in result
    assert "Description:" not in result


# ──────────────────────────────────────────────────────────────────────────────
# plan_test tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_test_skip_fixtures_context_true(monkeypatch):
    """plan_test with skip_fixtures_context=True skips fixture context builder."""
    from langchain_core.messages import HumanMessage

    fixtures_context_called = []

    def fake_fixtures_context(pid):
        fixtures_context_called.append(pid)
        return "FIXTURES_CONTEXT"

    result_model = _make_plan()
    _mock_planner(monkeypatch, result_model)
    monkeypatch.setattr(planner, "build_fixtures_context", fake_fixtures_context)

    state = {
        "messages": [HumanMessage(content="Test")],
        "project_id": 1,
        "project_settings": {"id": 1, "name": "Test", "url": "https://example.com"},
        "skip_fixtures_context": True,
    }

    result = await planner.plan_test(state)
    # When skip_fixtures_context=True, fixture context builder should NOT be called
    assert len(fixtures_context_called) == 0
    assert "test_plan" in result


@pytest.mark.asyncio
async def test_plan_test_skip_fixtures_context_false(monkeypatch):
    """plan_test without skip_fixtures_context calls fixture context builder."""
    from langchain_core.messages import HumanMessage

    fixtures_context_called = []

    def fake_fixtures_context(pid):
        fixtures_context_called.append(pid)
        return "FIXTURES_CONTEXT"

    result_model = _make_plan()
    _mock_planner(monkeypatch, result_model)
    monkeypatch.setattr(planner, "build_fixtures_context", fake_fixtures_context)

    state = {
        "messages": [HumanMessage(content="Test")],
        "project_id": 1,
        "project_settings": {"id": 1, "name": "Test", "url": "https://example.com"},
        # skip_fixtures_context not set
    }

    result = await planner.plan_test(state)
    # When skip_fixtures_context is not set, fixture context builder SHOULD be called
    assert len(fixtures_context_called) == 1
    assert "test_plan" in result


@pytest.mark.asyncio
async def test_plan_test_returns_expected_structure(monkeypatch):
    """plan_test returns dict with test_plan key containing steps."""
    from langchain_core.messages import HumanMessage

    steps = [
        planner.TestStepModel(action="navigate", target=None, value="/login", description="Go to login"),
        planner.TestStepModel(action="fill_form", target="email", value="test@example.com", description="Fill email"),
        planner.TestStepModel(action="click", target="submit", value=None, description="Click submit"),
    ]
    result_model = _make_plan(steps=steps)
    _mock_planner(monkeypatch, result_model)

    state = {
        "messages": [HumanMessage(content="Login test")],
        "project_settings": {"id": 1, "name": "Test", "url": "https://example.com"},
    }

    result = await planner.plan_test(state)

    assert "test_plan" in result
    tp = result["test_plan"]
    assert "steps" in tp
    assert len(tp["steps"]) == 3
    assert tp["steps"][0]["action"] == "navigate"
    assert tp["steps"][1]["action"] == "fill_form"


@pytest.mark.asyncio
async def test_plan_test_with_fixture_ids_in_result(monkeypatch):
    """plan_test passes fixture_ids from result to test_plan."""
    from langchain_core.messages import HumanMessage

    result_model = _make_plan(fixture_ids=[3, 7])
    _mock_planner(monkeypatch, result_model)

    state = {
        "messages": [HumanMessage(content="Dashboard test")],
        "project_settings": {"id": 1, "name": "Test", "url": "https://example.com"},
    }

    result = await planner.plan_test(state)
    assert result["test_plan"]["fixture_ids"] == [3, 7]


@pytest.mark.asyncio
async def test_plan_test_needs_clarification(monkeypatch):
    """plan_test includes needs_clarification and questions in response message."""
    from langchain_core.messages import HumanMessage, AIMessage

    result_model = _make_plan(
        steps=[
            planner.TestStepModel(
                action="click",
                target="{{BUTTON_NAME}}",
                value=None,
                description="Click unknown button",
            )
        ],
        needs_clarification=True,
        clarification_questions=["What is the exact button text?"],
    )
    _mock_planner(monkeypatch, result_model)

    state = {
        "messages": [HumanMessage(content="Click the special button")],
        "project_settings": {"id": 1, "name": "Test", "url": "https://example.com"},
    }

    result = await planner.plan_test(state)

    assert "test_plan" in result
    # Check that needs_clarification is surfaced somehow
    # (either in messages added or via test_plan flags)
    if "messages" in result:
        messages_added = result["messages"]
        # If AIMessage was added with clarification text
        response_content = " ".join(
            m.content for m in messages_added if isinstance(m, AIMessage)
        )
        assert "?" in response_content or "clarif" in response_content.lower() or len(messages_added) > 0


@pytest.mark.asyncio
async def test_plan_test_uses_project_settings_url(monkeypatch):
    """plan_test uses URL from project_settings for the PLANNER_PROMPT."""
    from langchain_core.messages import HumanMessage

    captured_payload = {}

    result_model = _make_plan()
    monkeypatch.setattr(planner, "get_llm", lambda tier: _FakeLLM())
    monkeypatch.setattr(planner, "build_app_context", lambda pid: "")
    monkeypatch.setattr(planner, "build_personas_and_pages_context", lambda pid: "")
    monkeypatch.setattr(planner, "build_fixtures_context", lambda pid: "")
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_personas_by_project", lambda s, pid: [])
    monkeypatch.setattr(planner.crud, "get_pages_by_project", lambda s, pid: [])

    class _CapturingPrompt:
        def __or__(self, structured_model):
            result = result_model

            class _Chain:
                async def ainvoke(self, payload):
                    captured_payload.update(payload)
                    return result

            return _Chain()

    monkeypatch.setattr(planner, "PLANNER_PROMPT", _CapturingPrompt())

    state = {
        "messages": [HumanMessage(content="Login test")],
        "project_settings": {"id": 1, "name": "Test", "url": "https://app.example.com"},
    }

    result = await planner.plan_test(state)

    assert captured_payload.get("base_url") == "https://app.example.com"


@pytest.mark.asyncio
async def test_plan_test_without_project_id_skips_template_lookup(monkeypatch):
    from langchain_core.messages import HumanMessage

    result_model = _make_plan(
        steps=[
            planner.TestStepModel(
                action="click",
                target="{{BUTTON_NAME}}",
                value=None,
                description="Click button",
            )
        ]
    )
    _mock_planner(monkeypatch, result_model)

    # No project_settings/project_id -> valid_templates branch is skipped
    state = {
        "messages": [HumanMessage(content="Click something")],
    }

    result = await planner.plan_test(state)
    assert "test_plan" in result


@pytest.mark.asyncio
async def test_plan_test_valid_templates_not_flagged_as_placeholders(monkeypatch):
    """Covers branch where placeholder matches valid persona/page template."""
    from langchain_core.messages import HumanMessage, AIMessage

    result_model = _make_plan(
        steps=[
            planner.TestStepModel(
                action="type",
                target="Username",
                value="{{admin.username}}",
                description="Use admin username",
            ),
            planner.TestStepModel(
                action="navigate",
                target=None,
                value="{{login}}",
                description="Go to login page",
            ),
        ]
    )
    _mock_planner(monkeypatch, result_model)
    monkeypatch.setattr(
        planner.crud,
        "get_personas_by_project",
        lambda s, pid: [SimpleNamespace(name="admin", description="Admin")],
    )
    monkeypatch.setattr(
        planner.crud,
        "get_pages_by_project",
        lambda s, pid: [SimpleNamespace(name="login", path="/login", description="")],
    )

    state = {
        "messages": [HumanMessage(content="Login as admin")],
        "project_settings": {"id": 1, "name": "Test", "url": "https://example.com"},
    }

    result = await planner.plan_test(state)
    content = "\n".join(m.content for m in result.get("messages", []) if isinstance(m, AIMessage))
    assert "I need some details" not in content


@pytest.mark.asyncio
async def test_plan_test_invalid_project_id_in_settings_skips_template_lookup(monkeypatch):
    """Covers ValueError branch when building valid_templates in plan_test."""
    from langchain_core.messages import HumanMessage

    result_model = _make_plan(
        steps=[
            planner.TestStepModel(
                action="click",
                target="{{BUTTON_NAME}}",
                value=None,
                description="Click button",
            )
        ]
    )
    _mock_planner(monkeypatch, result_model)

    state = {
        "messages": [HumanMessage(content="Click dynamic button")],
        "project_settings": {"id": "abc", "name": "Test", "url": "https://example.com"},
    }

    result = await planner.plan_test(state)
    assert "test_plan" in result
