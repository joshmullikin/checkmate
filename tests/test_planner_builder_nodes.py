from types import SimpleNamespace

import pytest

import agent.nodes.builder as builder
import agent.nodes.planner as planner


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakePrompt:
    def __init__(self, result):
        self._result = result

    def __or__(self, structured_model):
        class _Chain:
            def __init__(self, result):
                self._result = result

            async def ainvoke(self, payload):
                return self._result

        return _Chain(self._result)


def test_planner_context_builders(monkeypatch):
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        planner.crud,
        "get_project",
        lambda s, pid: SimpleNamespace(page_load_state="networkidle", base_prompt="App details"),
    )
    monkeypatch.setattr(
        planner.crud,
        "get_personas_by_project",
        lambda s, pid: [SimpleNamespace(name="admin", description="Admin user")],
    )
    monkeypatch.setattr(
        planner.crud,
        "get_pages_by_project",
        lambda s, pid: [SimpleNamespace(name="login", path="/login", description="Login page")],
    )
    monkeypatch.setattr(
        planner.crud,
        "get_fixtures_by_project",
        lambda s, pid: [
            SimpleNamespace(
                id=1,
                name="Login fixture",
                description="logs in",
                get_setup_steps=lambda: [{"action": "navigate"}, {"action": "fill_form"}],
            )
        ],
    )

    app_ctx = planner.build_app_context("10")
    pp_ctx = planner.build_personas_and_pages_context("10")
    fixtures_ctx = planner.build_fixtures_context("10")

    assert "networkidle" in app_ctx
    assert "admin.username" in pp_ctx
    assert "{{login}}" in pp_ctx
    assert "Fixture ID 1" in fixtures_ctx


@pytest.mark.asyncio
async def test_plan_test_with_mocked_chain(monkeypatch):
    result_model = planner.TestPlanModel(
        steps=[
            planner.TestStepModel(
                action="navigate",
                target=None,
                value="/login",
                description="Go to login",
            )
        ],
        expected_outcome="User reaches login page",
        fixture_ids=[1],
        needs_clarification=False,
        clarification_questions=None,
    )

    class _FakeLLM:
        def with_structured_output(self, model_cls):
            return object()

    monkeypatch.setattr(planner, "get_llm", lambda tier: _FakeLLM())
    monkeypatch.setattr(planner, "PLANNER_PROMPT", _FakePrompt(result_model))
    monkeypatch.setattr(planner, "build_app_context", lambda pid: "app")
    monkeypatch.setattr(planner, "build_personas_and_pages_context", lambda pid: "pp")
    monkeypatch.setattr(planner, "build_fixtures_context", lambda pid: "fx")
    monkeypatch.setattr(planner, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(planner.crud, "get_personas_by_project", lambda s, pid: [])
    monkeypatch.setattr(planner.crud, "get_pages_by_project", lambda s, pid: [])

    state = {
        "messages": [SimpleNamespace(type="human", content="test login")],
        "project_settings": {"id": 10, "url": "https://example.com"},
        "extracted_feature": "auth",
    }

    out = await planner.plan_test(state)
    assert "test_plan" in out
    assert out["test_plan"]["expected_outcome"] == "User reaches login page"
    assert len(out["test_plan"]["steps"]) == 1


def test_builder_context_builders(monkeypatch):
    monkeypatch.setattr(builder, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(
        builder.crud,
        "get_project",
        lambda s, pid: SimpleNamespace(page_load_state="load", base_prompt="Builder app context"),
    )
    monkeypatch.setattr(
        builder.crud,
        "get_personas_by_project",
        lambda s, pid: [SimpleNamespace(name="svc", description="service", credential_type="api_key")],
    )
    monkeypatch.setattr(
        builder.crud,
        "get_pages_by_project",
        lambda s, pid: [SimpleNamespace(name="home", path="/home", description="Home")],
    )
    monkeypatch.setattr(
        builder.crud,
        "get_test_data_by_project",
        lambda s, pid: [SimpleNamespace(name="seed", description="seed")],
    )
    monkeypatch.setattr(
        builder.crud,
        "get_fixtures_by_project",
        lambda s, pid: [
            SimpleNamespace(
                id=9,
                name="Warmup",
                description="Warm cache",
                get_setup_steps=lambda: [{"action": "navigate"}],
            )
        ],
    )

    app_ctx = builder.build_app_context(10)
    pp_ctx = builder.build_personas_and_pages_context(10)
    fixtures_ctx = builder.build_fixtures_context(10)

    assert "Builder app context" in app_ctx
    assert "svc.api_key" in pp_ctx
    assert "data.seed" in pp_ctx
    assert "Fixture ID 9" in fixtures_ctx


@pytest.mark.asyncio
async def test_build_test_case_with_mocked_chain(monkeypatch):
    response = builder.BuilderResponse(
        test_case=builder.TestCaseModel(
            name="Login smoke",
            natural_query="Login flow",
            priority="medium",
            tags=["smoke"],
            steps=[
                builder.TestStepModel(
                    action="navigate",
                    target=None,
                    value="/login",
                    description="Go to login",
                )
            ],
            fixture_ids=[1],
        ),
        message=None,
        needs_clarification=False,
        suggested_credentials=[],
    )

    class _FakeLLM:
        def with_structured_output(self, model_cls):
            return object()

    monkeypatch.setattr(builder, "get_llm", lambda tier: _FakeLLM())
    monkeypatch.setattr(builder, "BUILDER_PROMPT", _FakePrompt(response))
    monkeypatch.setattr(builder, "build_app_context", lambda pid: "app")
    monkeypatch.setattr(builder, "build_personas_and_pages_context", lambda pid: "pp")
    monkeypatch.setattr(builder, "build_fixtures_context", lambda pid: "fx")

    result = await builder.build_test_case(
        current_message="add login steps",
        previous_messages=["create a smoke test"],
        current_test_case={"name": "Draft", "steps": []},
        project_name="My Project",
        base_url="https://example.com",
        project_id=10,
    )

    assert result.test_case.name == "Login smoke"
    assert len(result.test_case.steps) == 1


@pytest.mark.asyncio
async def test_build_test_case_with_original_steps_and_current_steps(monkeypatch):
    """Test build_test_case with original_steps (line 396-402) and current steps (line 406-418)."""
    response = builder.BuilderResponse(
        test_case=builder.TestCaseModel(
            name="Login full",
            natural_query="Login flow",
            priority="medium",
            tags=["smoke"],
            steps=[
                builder.TestStepModel(
                    action="navigate",
                    target=None,
                    value="/login",
                    description="Go to login",
                )
            ],
            fixture_ids=[],
        ),
        message=None,
        needs_clarification=False,
        suggested_credentials=[],
    )

    class _FakeLLM:
        def with_structured_output(self, model_cls):
            return object()

    monkeypatch.setattr(builder, "get_llm", lambda tier: _FakeLLM())
    monkeypatch.setattr(builder, "BUILDER_PROMPT", _FakePrompt(response))
    monkeypatch.setattr(builder, "build_app_context", lambda pid: "app")
    monkeypatch.setattr(builder, "build_personas_and_pages_context", lambda pid: "pp")
    monkeypatch.setattr(builder, "build_fixtures_context", lambda pid: "fx")

    # Test with original_steps (triggers lines 396-402) AND steps (triggers lines 406-418)
    result = await builder.build_test_case(
        current_message="update test",
        previous_messages=[],
        current_test_case={
            "name": "My Test",
            "natural_query": "Login and verify",
            "priority": "high",
            "tags": ["smoke"],
            "original_steps": [
                {"action": "navigate", "description": "Go to login", "target": None, "value": "/login"},
            ],
            "steps": [
                {"action": "navigate", "description": "Go to login", "target": None, "value": "/login"},
                {"action": "type", "description": "Enter email", "target": "email", "value": "x@y.com"},
            ],
        },
        project_name="My Project",
        base_url="https://example.com",
        project_id=10,
    )

    assert result.test_case.name == "Login full"


@pytest.mark.asyncio
async def test_build_test_case_no_previous_messages(monkeypatch):
    """Test build_test_case with empty previous_messages (else branch line 390)."""
    response = builder.BuilderResponse(
        test_case=builder.TestCaseModel(
            name="Empty test",
            natural_query="Empty",
            priority="low",
            tags=[],
            steps=[],
            fixture_ids=[],
        ),
        message=None,
        needs_clarification=False,
        suggested_credentials=[],
    )

    class _FakeLLM:
        def with_structured_output(self, model_cls):
            return object()

    monkeypatch.setattr(builder, "get_llm", lambda tier: _FakeLLM())
    monkeypatch.setattr(builder, "BUILDER_PROMPT", _FakePrompt(response))
    monkeypatch.setattr(builder, "build_app_context", lambda pid: "app")
    monkeypatch.setattr(builder, "build_personas_and_pages_context", lambda pid: "pp")
    monkeypatch.setattr(builder, "build_fixtures_context", lambda pid: "fx")

    result = await builder.build_test_case(
        current_message="start fresh",
        previous_messages=[],  # triggers else branch
        current_test_case=None,  # triggers else in current_tc check
        project_name="Empty",
        base_url="https://example.com",
        project_id=10,
    )
    assert result.test_case.name == "Empty test"


def test_builder_context_builders_no_project_id(monkeypatch):
    """Test build_*_context functions with no project_id return empty/default."""
    assert builder.build_app_context(None) == ""
    assert builder.build_app_context(0) == ""
    result = builder.build_personas_and_pages_context(None)
    assert "No credentials" in result
    assert builder.build_fixtures_context(None) == ""


def test_builder_context_builders_project_not_found(monkeypatch):
    """Test build_*_context when project is None (project not found)."""
    monkeypatch.setattr(builder, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(builder.crud, "get_project", lambda s, pid: None)
    monkeypatch.setattr(builder.crud, "get_personas_by_project", lambda s, pid: [])
    monkeypatch.setattr(builder.crud, "get_pages_by_project", lambda s, pid: [])
    monkeypatch.setattr(builder.crud, "get_test_data_by_project", lambda s, pid: [])
    monkeypatch.setattr(builder.crud, "get_fixtures_by_project", lambda s, pid: [])

    # When project is None, build_app_context returns ""
    result = builder.build_app_context(10)
    assert result == ""

    # build_personas_and_pages_context returns default when no personas/pages
    pp_result = builder.build_personas_and_pages_context(10)
    assert "No credentials" in pp_result

    # build_fixtures_context returns "" when no fixtures
    fx_result = builder.build_fixtures_context(10)
    assert fx_result == ""


def test_builder_context_builders_token_and_custom_personas(monkeypatch):
    """Test build_personas_and_pages_context with token and custom credential types."""
    monkeypatch.setattr(builder, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(builder.crud, "get_project", lambda s, pid: SimpleNamespace(base_prompt="", page_load_state="load"))
    monkeypatch.setattr(builder.crud, "get_personas_by_project", lambda s, pid: [
        SimpleNamespace(name="bearer", description="", credential_type="token"),
        SimpleNamespace(name="custom_user", description="", credential_type="custom"),
    ])
    monkeypatch.setattr(builder.crud, "get_pages_by_project", lambda s, pid: [])
    monkeypatch.setattr(builder.crud, "get_test_data_by_project", lambda s, pid: [])

    pp_result = builder.build_personas_and_pages_context(10)
    assert "bearer.token" in pp_result
    assert "custom_user.<field_name>" in pp_result


def test_builder_context_builders_fixtures_over_3_steps(monkeypatch):
    """Test build_fixtures_context with fixture having >3 steps shows ellipsis."""
    monkeypatch.setattr(builder, "Session", lambda engine: _DummySession())
    monkeypatch.setattr(builder.crud, "get_fixtures_by_project", lambda s, pid: [
        SimpleNamespace(
            id=1,
            name="Big fixture",
            description="many steps",
            get_setup_steps=lambda: [
                {"action": "navigate"}, {"action": "type"}, {"action": "click"}, {"action": "assert"}
            ],
        )
    ])

    fx_result = builder.build_fixtures_context(10)
    assert "..." in fx_result
    assert "4 steps total" in fx_result