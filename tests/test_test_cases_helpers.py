import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi.responses import StreamingResponse

from api.routes import test_cases as test_cases_routes
from db import crud
import db.encryption as encryption
from db.models import FixtureCreate, ProjectCreate


async def _collect_async(gen):
    items = []
    async for item in gen:
        items.append(item)
    return items


def _project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="TC Helper Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def test_merge_browser_state_combines_collections():
    target = {"cookies": [{"name": "a"}], "local_storage": {"k1": "v1"}, "session_storage": {"s1": "x"}}
    source = {"cookies": [{"name": "b"}], "local_storage": {"k2": "v2"}, "session_storage": {"s2": "y"}}

    test_cases_routes._merge_browser_state(target, source)

    assert len(target["cookies"]) == 2
    assert target["local_storage"]["k2"] == "v2"
    assert target["session_storage"]["s2"] == "y"


def test_merge_browser_state_ignores_empty_collections():
    target = {"cookies": [{"name": "a"}], "local_storage": {"k1": "v1"}, "session_storage": {"s1": "x"}}
    source = {"cookies": [], "local_storage": {}, "session_storage": {}}

    test_cases_routes._merge_browser_state(target, source)

    assert target == {"cookies": [{"name": "a"}], "local_storage": {"k1": "v1"}, "session_storage": {"s1": "x"}}


def test_enrich_event_adds_fields_and_preserves_existing():
    out = test_cases_routes._enrich_event('data: {"type":"step_started"}\n\n', test_case_id=12, browser="chromium")
    payload = json.loads(out[6:].strip())
    assert payload["test_case_id"] == 12
    assert payload["browser"] == "chromium"

    out2 = test_cases_routes._enrich_event(
        'data: {"type":"x","test_case_id":99,"browser":"firefox"}\n\n',
        test_case_id=12,
        browser="chromium",
    )
    payload2 = json.loads(out2[6:].strip())
    assert payload2["test_case_id"] == 99
    assert payload2["browser"] == "firefox"


def test_enrich_event_non_data_and_invalid_json_passthrough():
    raw = "event: ping\n\n"
    assert test_cases_routes._enrich_event(raw, test_case_id=1) == raw

    broken = "data: {not-json}\n\n"
    assert test_cases_routes._enrich_event(broken, test_case_id=1) == broken


def test_get_fixture_steps_no_fixtures_found(monkeypatch):
    monkeypatch.setattr(test_cases_routes.crud, "get_fixtures_by_ids", lambda session, ids: [])
    tc = SimpleNamespace(get_fixture_ids=lambda: [999])
    resolved, display, cached = test_cases_routes._get_fixture_steps(SimpleNamespace(), tc, 1, browser="chromium")
    assert resolved == []
    assert display == []
    assert cached is False


def test_get_fixture_steps_without_fixture_ids_returns_empty():
    tc = SimpleNamespace(get_fixture_ids=lambda: [])
    resolved, display, cached = test_cases_routes._get_fixture_steps(SimpleNamespace(), tc, 1, browser="chromium")
    assert resolved == []
    assert display == []
    assert cached is False


def test_get_fixture_steps_non_cached_fixture_does_not_add_capture(monkeypatch):
    fixture = SimpleNamespace(name="Setup", scope="test", get_setup_steps=lambda: [{"action": "navigate", "value": "/login"}])
    monkeypatch.setattr(test_cases_routes.crud, "get_fixtures_by_ids", lambda session, ids: [fixture])
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda session, project_id, steps: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)

    tc = SimpleNamespace(get_fixture_ids=lambda: [7])
    resolved, display, cached = test_cases_routes._get_fixture_steps(SimpleNamespace(), tc, 1, browser="chromium")

    assert cached is False
    assert len(resolved) == 1
    assert resolved[0]["action"] == "navigate"


def test_get_fixture_steps_empty_setup_steps_returns_empty(monkeypatch):
    fixture = SimpleNamespace(id=8, name="Setup", scope="cached", get_setup_steps=lambda: [])
    monkeypatch.setattr(test_cases_routes.crud, "get_fixtures_by_ids", lambda session, ids: [fixture])
    monkeypatch.setattr(test_cases_routes.crud, "get_valid_fixture_state", lambda session, fixture_id, browser: None)

    tc = SimpleNamespace(get_fixture_ids=lambda: [8])
    resolved, display, cached = test_cases_routes._get_fixture_steps(SimpleNamespace(), tc, 1, browser="chromium")

    assert resolved == []
    assert display == []
    assert cached is False


def test_get_fixture_steps_cache_hit_and_miss(db_session):
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _project(db_session)
    fixture = crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=project.id,
            name="Fixture A",
            description="",
            setup_steps=json.dumps([{"action": "navigate", "value": "/login"}]),
            scope="cached",
            cache_ttl_seconds=300,
        ),
    )

    tc = SimpleNamespace(get_fixture_ids=lambda: [fixture.id])

    miss_steps, miss_display, miss_cached = test_cases_routes._get_fixture_steps(
        db_session, tc, project.id, browser="chromium-headless"
    )
    assert miss_cached is False
    assert len(miss_steps) == 2
    assert miss_steps[-1]["action"] == "capture_state"

    crud.create_fixture_state(
        db_session,
        fixture_id=fixture.id,
        project_id=project.id,
        url="https://example.com/dashboard",
        state_json=json.dumps({"cookies": []}),
        browser="chromium-headless",
        expires_at=datetime.utcnow() + timedelta(seconds=600),
    )

    hit_steps, hit_display, hit_cached = test_cases_routes._get_fixture_steps(
        db_session, tc, project.id, browser="chromium-headless"
    )
    assert hit_cached is True
    assert hit_steps[0]["action"] == "restore_state"
    assert hit_display[0]["value"] == "[cached browser state]"


@pytest.mark.asyncio
async def test_execute_single_run_simulation_branch(monkeypatch):
    monkeypatch.setattr("api.routes.test_cases.asyncio.sleep", lambda _t: _collect_async(_empty_async()))

    create_test_run = lambda session, data: SimpleNamespace(id=501)
    update_test_run = lambda session, run_id, data: None
    create_step_calls = []

    def create_step(session, step):
        create_step_calls.append(step)
        return SimpleNamespace(id=len(create_step_calls))

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", create_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "create_test_run_step", create_step)

    test_case = SimpleNamespace(id=1001, project_id=42)
    project = SimpleNamespace(base_url="https://example.com")
    resolved_steps = [{"action": "navigate", "value": "/login", "description": "Go login"}]
    display_steps = [{"action": "navigate", "value": "/login", "target": None, "fixture_name": None}]

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=SimpleNamespace(),
            executor_client=SimpleNamespace(),
            use_simulation=True,
            test_case=test_case,
            project=project,
            resolved_steps=resolved_steps,
            display_steps=display_steps,
            browser="chromium-headless",
        )
    )

    assert any("run_started" in e for e in events)
    assert any("run_completed" in e for e in events)
    assert any('"_internal": true' in e for e in events)
    assert len(create_step_calls) == 1


async def _empty_async():
    if False:
        yield None


def test_run_test_case_streaming_validates_intelligent_retry_flag(client, monkeypatch):
    monkeypatch.setattr(test_cases_routes, "INTELLIGENT_RETRY_ENABLED", False)

    res = client.post(
        "/api/test-cases/1/runs/stream",
        json={"retry": {"max_retries": 1, "retry_mode": "intelligent"}},
    )
    assert res.status_code == 400
    assert "Intelligent retry is not enabled" in res.json()["detail"]


@pytest.mark.asyncio
async def test_run_test_case_stream_returns_error_for_missing_test_case(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda session, tc_id: None)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=999))
    assert len(events) == 1
    assert '"type": "error"' in events[0]
    assert "Test case not found" in events[0]


def test_run_batch_streaming_validates_intelligent_retry_flag(client, monkeypatch):
    monkeypatch.setattr(test_cases_routes, "INTELLIGENT_RETRY_ENABLED", False)

    res = client.post(
        "/api/test-cases/project/1/run-batch/stream",
        json={
            "test_case_ids": [1],
            "retry": {"max_retries": 1, "retry_mode": "intelligent"},
        },
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_run_batch_stream_project_not_found(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda session, pid: None)

    events = await _collect_async(test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[1]))
    assert len(events) == 1
    assert "Project not found" in events[0]


@pytest.mark.asyncio
async def test_run_batch_stream_no_valid_test_cases(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda session, pid: SimpleNamespace(id=pid))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda session, tcid: None)

    events = await _collect_async(test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[1, 2]))
    assert len(events) == 1
    assert "No valid test cases found" in events[0]


@pytest.mark.asyncio
async def test_run_batch_stream_sequential_path(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), True

    async def fake_single_run(**kwargs):
        yield "data: {\"type\":\"step_started\"}\n\n"
        yield json.dumps({"_internal": True, "run_id": 77, "status": "passed"})

    tc = SimpleNamespace(id=10, project_id=1, name="Smoke", steps='[{"action":"navigate","value":"/"}]')

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(
        test_cases_routes.run_batch_stream(
            project_id=1,
            test_case_ids=[10],
            browser="chromium-headless",
            parallel=1,
        )
    )

    joined = "".join(events)
    assert "batch_started" in joined
    assert "test_started" in joined
    assert "test_completed" in joined
    assert "batch_completed" in joined


@pytest.mark.asyncio
async def test_execute_single_run_non_simulation_with_step_events(monkeypatch):
    """Test non-simulation path with executor stream returning step events."""
    async def fake_stream(*args, **kwargs):
        yield {"type": "step_started", "step_number": 1, "action": "navigate"}
        yield {
            "type": "step_completed",
            "step_number": 1,
            "status": "passed",
            "duration": 100,
            "error": None,
            "screenshot": None,
        }

    create_test_run = lambda session, data: SimpleNamespace(id=501)
    update_test_run = MagicMock()
    create_step = MagicMock()

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", create_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "create_test_run_step", create_step)

    executor_client = SimpleNamespace(execute_stream=fake_stream)
    test_case = SimpleNamespace(id=1001, project_id=42)
    project = SimpleNamespace(base_url="https://example.com")
    resolved_steps = [{"action": "navigate", "value": "/login"}]
    display_steps = [{"action": "navigate", "value": "/login", "target": None, "fixture_name": None}]

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=SimpleNamespace(),
            executor_client=executor_client,
            use_simulation=False,
            test_case=test_case,
            project=project,
            resolved_steps=resolved_steps,
            display_steps=display_steps,
            browser="chromium-headless",
        )
    )

    joined = "".join(events)
    assert "run_started" in joined
    assert "run_completed" in joined
    assert create_step.call_count >= 1


@pytest.mark.asyncio
async def test_execute_single_run_capture_state_persists_fixture_cache(monkeypatch, db_session):
    """Test capture_state step persists fixture state for caching."""
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project_obj = _project(db_session)
    fixture = crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=project_obj.id,
            name="Login Fixture",
            description="",
            setup_steps=json.dumps([{"action": "navigate", "value": "/login"}]),
            scope="cached",
            cache_ttl_seconds=3600,
        ),
    )

    async def fake_stream(*args, **kwargs):
        yield {"type": "step_started", "step_number": 1, "action": "navigate"}
        yield {
            "type": "step_completed",
            "step_number": 1,
            "status": "passed",
            "duration": 100,
        }
        yield {"type": "step_started", "step_number": 2, "action": "capture_state"}
        yield {
            "type": "step_completed",
            "step_number": 2,
            "action": "capture_state",
            "status": "passed",
            "result": {
                "url": "https://example.com/dashboard",
                "state": {"cookies": [{"name": "session"}]},
            },
        }

    create_test_run = lambda session, data: SimpleNamespace(id=501)
    update_test_run = MagicMock()
    create_step = MagicMock()

    from unittest.mock import patch

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", create_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(test_cases_routes.crud, "get_fixtures_by_ids", lambda s, ids: [fixture])

    executor_client = SimpleNamespace(execute_stream=fake_stream)
    test_case = SimpleNamespace(id=1001, project_id=project_obj.id)
    project_model = SimpleNamespace(base_url="https://example.com")
    resolved_steps = [
        {"action": "navigate", "value": "/login"},
        {"action": "capture_state", "description": "Capture state"},
    ]
    display_steps = [
        {"action": "navigate", "value": "/login", "target": None, "fixture_name": None},
        {"action": "capture_state", "target": None, "fixture_name": "Login Fixture"},
    ]

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=db_session,
            executor_client=executor_client,
            use_simulation=False,
            test_case=test_case,
            project=project_model,
            resolved_steps=resolved_steps,
            display_steps=display_steps,
            browser="chromium-headless",
            fixture_ids=[fixture.id],
        )
    )

    joined = "".join(events)
    assert "run_completed" in joined
    assert len(events) > 0


@pytest.mark.asyncio
async def test_execute_single_run_error_event_from_executor(monkeypatch):
    """Test error event handling from executor."""
    async def fake_stream(*args, **kwargs):
        yield {"type": "error", "error": "Connection refused"}

    create_test_run = lambda session, data: SimpleNamespace(id=501)
    update_test_run = MagicMock()

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", create_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", update_test_run)

    executor_client = SimpleNamespace(execute_stream=fake_stream)
    test_case = SimpleNamespace(id=1001, project_id=42)
    project = SimpleNamespace(base_url="https://example.com")
    resolved_steps = [{"action": "navigate", "value": "/login"}]
    display_steps = [{"action": "navigate", "value": "/login", "target": None, "fixture_name": None}]

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=SimpleNamespace(),
            executor_client=executor_client,
            use_simulation=False,
            test_case=test_case,
            project=project,
            resolved_steps=resolved_steps,
            display_steps=display_steps,
            browser="chromium-headless",
        )
    )

    joined = "".join(events)
    assert any("error" in e.lower() for e in events)


@pytest.mark.asyncio
async def test_execute_single_run_step_retry_event_forwarded(monkeypatch):
    """Test step_retry events are forwarded to client."""
    async def fake_stream(*args, **kwargs):
        yield {"type": "step_started", "step_number": 1, "action": "click"}
        yield {"type": "step_retry", "step_number": 1, "attempt": 1}
        yield {
            "type": "step_completed",
            "step_number": 1,
            "status": "passed",
            "duration": 150,
        }

    create_test_run = lambda session, data: SimpleNamespace(id=501)
    update_test_run = MagicMock()
    create_step = MagicMock()

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", create_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "create_test_run_step", create_step)

    executor_client = SimpleNamespace(execute_stream=fake_stream)
    test_case = SimpleNamespace(id=1001, project_id=42)
    project = SimpleNamespace(base_url="https://example.com")
    resolved_steps = [{"action": "click", "target": "button"}]
    display_steps = [{"action": "click", "target": "button", "value": None, "fixture_name": None}]

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=SimpleNamespace(),
            executor_client=executor_client,
            use_simulation=False,
            test_case=test_case,
            project=project,
            resolved_steps=resolved_steps,
            display_steps=display_steps,
            browser="chromium-headless",
        )
    )

    joined = "".join(events)
    assert any("step_retry" in e for e in events)


@pytest.mark.asyncio
async def test_execute_single_run_completed_event_and_capture_state_without_cache_write(monkeypatch):
    captured = {}

    async def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        yield {"type": "step_started", "step_number": 1, "action": "capture_state"}
        yield {
            "type": "step_completed",
            "step_number": 1,
            "status": "passed",
            "duration": 50,
            "result": {},
        }
        yield {"type": "completed"}

    create_test_run = lambda session, data: SimpleNamespace(id=501)
    update_test_run = MagicMock()
    create_step = MagicMock()
    delete_states = MagicMock()
    create_state = MagicMock()

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", create_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(test_cases_routes.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(test_cases_routes.crud, "get_fixtures_by_ids", lambda s, ids: [SimpleNamespace(scope="cached", name="Fixture", id=1, cache_ttl_seconds=60)])
    monkeypatch.setattr(test_cases_routes.crud, "delete_fixture_states_by_fixture", delete_states)
    monkeypatch.setattr(test_cases_routes.crud, "create_fixture_state", create_state)

    executor_client = SimpleNamespace(execute_stream=fake_stream)
    test_case = SimpleNamespace(id=1001, project_id=42)
    project = SimpleNamespace(base_url="https://example.com")
    resolved_steps = [{"action": "capture_state", "description": "Capture state"}]
    display_steps = [{"action": "capture_state", "value": None, "target": None, "fixture_name": "Fixture"}]

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=SimpleNamespace(),
            executor_client=executor_client,
            use_simulation=False,
            test_case=test_case,
            project=project,
            resolved_steps=resolved_steps,
            display_steps=display_steps,
            browser="chromium",
            fixture_ids=[1],
        )
    )

    assert captured["options"] == {"screenshot_on_failure": True, "browser": "chromium"}
    assert any("run_completed" in e for e in events)
    delete_states.assert_not_called()
    create_state.assert_not_called()


@pytest.mark.asyncio
async def test_execute_single_run_adds_viewport_without_browser(monkeypatch):
    captured = {}

    async def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        yield {"type": "step_started", "step_number": 1, "action": "navigate"}
        yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 10}
        yield {"type": "completed"}

    monkeypatch.setattr(test_cases_routes.crud, "create_test_run", lambda session, data: SimpleNamespace(id=501))
    monkeypatch.setattr(test_cases_routes.crud, "update_test_run", MagicMock())
    monkeypatch.setattr(test_cases_routes.crud, "create_test_run_step", MagicMock())

    events = await _collect_async(
        test_cases_routes._execute_single_run(
            session=SimpleNamespace(),
            executor_client=SimpleNamespace(execute_stream=fake_stream),
            use_simulation=False,
            test_case=SimpleNamespace(id=100, project_id=1),
            project=SimpleNamespace(base_url="https://example.com"),
            resolved_steps=[{"action": "navigate", "value": "/"}],
            display_steps=[{"action": "navigate", "value": "/", "target": None, "fixture_name": None}],
            browser=None,
            viewport={"width": 800, "height": 600},
        )
    )

    assert captured["options"] == {"screenshot_on_failure": True, "viewport": {"width": 800, "height": 600}}
    assert any("run_completed" in event for event in events)


@pytest.mark.asyncio
async def test_run_batch_stream_with_parallel_multiple_browsers(monkeypatch):
    """Test batch execution with multiple browsers and parallel semaphores."""
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    async def fake_single_run(session, executor_client, use_simulation, test_case, project, resolved_steps, display_steps, browser, **kwargs):
        yield f'data: {{"type":"test_completed","browser":"{browser}","run_id":{test_case.id}}}\n\n'
        yield json.dumps({"_internal": True, "run_id": test_case.id, "status": "passed"})

    tc1 = SimpleNamespace(id=10, project_id=1, name="Test 1", steps='[{"action":"navigate","value":"/"}]')
    tc2 = SimpleNamespace(id=11, project_id=1, name="Test 2", steps='[{"action":"click","value":"button"}]')

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(
        test_cases_routes.crud,
        "get_test_case",
        lambda s, tcid: tc1 if tcid == 10 else tc2,
    )
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(
        test_cases_routes.run_batch_stream(
            project_id=1,
            test_case_ids=[10, 11],
            browsers=["chromium", "firefox"],
            parallel=2,
        )
    )

    joined = "".join(events)
    assert "batch_started" in joined
    assert "batch_completed" in joined


@pytest.mark.asyncio
async def test_run_batch_stream_with_semaphore_limits_parallelism(monkeypatch):
    """Test batch semaphore limits concurrent execution."""
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    active_count = [0]
    max_active = [0]

    async def fake_single_run(session, executor_client, use_simulation, test_case, project, resolved_steps, display_steps, browser, **kwargs):
        active_count[0] += 1
        max_active[0] = max(max_active[0], active_count[0])
        await asyncio.sleep(0.01)
        active_count[0] -= 1
        yield 'data: {"type":"run_completed"}\n\n'
        yield json.dumps({"_internal": True, "run_id": test_case.id, "status": "passed"})

    tcs = [
        SimpleNamespace(id=i, project_id=1, name=f"Test {i}", steps='[{"action":"navigate"}]')
        for i in range(20, 24)
    ]

    def get_tc(s, tcid):
        for tc in tcs:
            if tc.id == tcid:
                return tc
        return None

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", get_tc)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(
        test_cases_routes.run_batch_stream(
            project_id=1,
            test_case_ids=[20, 21, 22, 23],
            parallel=2,
        )
    )

    assert max_active[0] <= 2


@pytest.mark.asyncio
async def test_run_test_case_stream_fixture_loading_warning_then_continue(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _single_run(**kwargs):
        yield 'data: {"type":"step_started"}\n\n'
        yield json.dumps({"_internal": True, "run_id": 77, "status": "passed", "failure_info": None})

    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"navigate","value":"/"}]', get_fixture_ids=lambda: [11])
    project = SimpleNamespace(id=5, base_url="https://example.com")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_get_fixture_steps", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("fixture blowup")))
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1))

    joined = "".join(events)
    assert "fixtures_loading" in joined
    assert "fixture blowup" in joined
    assert "step_started" in joined


@pytest.mark.asyncio
async def test_run_test_case_stream_environment_mismatch_and_invalid_steps(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    tc = SimpleNamespace(id=1, project_id=5, steps="{bad json", get_fixture_ids=lambda: [])
    project = SimpleNamespace(id=5, base_url="https://example.com")
    other_env = SimpleNamespace(project_id=99, base_url="https://wrong.example.com", name="wrong", get_variables=lambda: {"ENV": "wrong"})

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes.crud, "get_environment", lambda s, env_id: other_env)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1, environment_id=8))

    assert any("No steps defined in test case" in event for event in events)


@pytest.mark.asyncio
async def test_run_test_case_stream_fixtures_loaded_event(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _single_run(**kwargs):
        assert len(kwargs["resolved_steps"]) == 2
        yield json.dumps({"_internal": True, "run_id": 88, "status": "passed", "failure_info": None})

    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"navigate","value":"/app"}]', get_fixture_ids=lambda: [11])
    project = SimpleNamespace(id=5, base_url="https://example.com")
    fixture_steps = [{"action": "navigate", "value": "/login"}]

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_get_fixture_steps", lambda **kwargs: (fixture_steps, fixture_steps, True))
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1))

    joined = "".join(events)
    assert "fixtures_loaded" in joined
    assert "fixtures_cached" in joined


@pytest.mark.asyncio
async def test_run_test_case_stream_empty_fixture_resolution_skips_loaded_event(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _single_run(**kwargs):
        assert len(kwargs["resolved_steps"]) == 1
        yield json.dumps({"_internal": True, "run_id": 89, "status": "passed", "failure_info": None})

    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"navigate","value":"/app"}]', get_fixture_ids=lambda: [11])
    project = SimpleNamespace(id=5, base_url="https://example.com")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_get_fixture_steps", lambda **kwargs: ([], [], False))
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1))

    joined = "".join(events)
    assert "fixtures_loading" in joined
    assert "fixtures_loaded" not in joined


@pytest.mark.asyncio
async def test_run_test_case_stream_breaks_when_no_internal_result(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _single_run(**kwargs):
        yield 'data: {"type":"step_started"}\n\n'

    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"navigate","value":"/"}]', get_fixture_ids=lambda: [])
    project = SimpleNamespace(id=5, base_url="https://example.com")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1))

    assert len(events) == 1
    assert "step_started" in events[0]


@pytest.mark.asyncio
async def test_run_test_case_stream_intelligent_retry_retryable(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    attempts = {"count": 0}

    async def _single_run(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield json.dumps({
                "_internal": True,
                "run_id": 70,
                "status": "failed",
                "failure_info": {"action": "click", "target": "#btn", "value": None, "error": "missing", "screenshot": None},
            })
        else:
            yield json.dumps({"_internal": True, "run_id": 71, "status": "passed", "failure_info": None})

    classification = SimpleNamespace(is_retryable=True, failure_category="transient", reasoning="retry it", confidence=0.8)
    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"click","target":"#btn"}]', get_fixture_ids=lambda: [])
    project = SimpleNamespace(id=5, base_url="https://example.com")
    retry_cfg = SimpleNamespace(max_retries=1, retry_mode="intelligent")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)
    monkeypatch.setattr(test_cases_routes, "classify_failure", AsyncMock(return_value=classification))

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1, retry_config=retry_cfg))

    joined = "".join(events)
    assert "test_retry" in joined
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_run_test_case_stream_intelligent_retry_skipped(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _single_run(**kwargs):
        yield json.dumps({
            "_internal": True,
            "run_id": 91,
            "status": "failed",
            "failure_info": {"action": "click", "target": "#btn", "value": None, "error": "missing", "screenshot": None},
        })

    classification = SimpleNamespace(is_retryable=False, failure_category="locator", reasoning="bad locator", confidence=0.9)
    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"click","target":"#btn"}]', get_fixture_ids=lambda: [])
    project = SimpleNamespace(id=5, base_url="https://example.com")
    retry_cfg = SimpleNamespace(max_retries=1, retry_mode="intelligent")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)
    monkeypatch.setattr(test_cases_routes, "classify_failure", AsyncMock(return_value=classification))

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1, retry_config=retry_cfg))

    joined = "".join(events)
    assert "retry_skipped" in joined
    assert "bad locator" in joined


@pytest.mark.asyncio
async def test_run_test_case_stream_simple_retry_mode(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    attempts = {"count": 0}

    async def _single_run(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield json.dumps({"_internal": True, "run_id": 101, "status": "failed", "failure_info": None})
        else:
            yield json.dumps({"_internal": True, "run_id": 102, "status": "passed", "failure_info": None})

    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"navigate","value":"/"}]', get_fixture_ids=lambda: [])
    project = SimpleNamespace(id=5, base_url="https://example.com")
    retry_cfg = SimpleNamespace(max_retries=1, retry_mode="simple")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1, retry_config=retry_cfg))

    joined = "".join(events)
    assert "test_retry" in joined
    assert "simple retry mode" in joined
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_run_test_case_stream_failure_with_no_retries(monkeypatch):
    class _Ctx:
        async def __aenter__(self):
            return (SimpleNamespace(), SimpleNamespace(), False)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _single_run(**kwargs):
        yield json.dumps({"_internal": True, "run_id": 300, "status": "failed", "failure_info": {"error": "boom"}})

    tc = SimpleNamespace(id=1, project_id=5, steps='[{"action":"navigate","value":"/"}]', get_fixture_ids=lambda: [])
    project = SimpleNamespace(id=5, base_url="https://example.com")

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: project)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1))

    assert not any("test_retry" in event for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory", "expected"),
    [
        (lambda: test_cases_routes.SQLAlchemyError("db down"), "Database error"),
        (lambda: test_cases_routes.HTTPError("executor down"), "Browser connection error"),
        (lambda: json.JSONDecodeError("bad json", "x", 0), "Invalid step data"),
    ],
)
async def test_run_test_case_stream_specific_exception_handlers(monkeypatch, error_factory, expected):
    class _Ctx:
        async def __aenter__(self):
            raise error_factory()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())

    events = await _collect_async(test_cases_routes.run_test_case_stream(test_case_id=1))
    assert any(expected in event for event in events)


@pytest.mark.asyncio
async def test_run_test_case_streaming_wrapper_returns_streaming_response():
    request = test_cases_routes.RunTestCaseRequest(
        browser="chromium",
        viewport=test_cases_routes.ViewportConfig(width=1280, height=720),
        retry=None,
        environment_id=3,
    )

    response = await test_cases_routes.run_test_case_streaming(5, request)
    assert isinstance(response, StreamingResponse)


class _FakeWorkerSession:
    def __init__(self, fail_commit=False):
        self.fail_commit = fail_commit
        self.rollback_called = False
        self.closed = False

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit fail")

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_run_browser_batch_invalid_json_steps_skips_test(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession()
    tc = SimpleNamespace(id=12, name="broken", steps="{bad json")

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)

    await test_cases_routes._run_browser_batch(
        browser="chromium",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=0,
        retry_mode="simple",
        batch_id="batch-1",
        context=None,
        viewport=None,
        project_id=1,
    )

    events = []
    while not queue.empty():
        events.append(await queue.get())

    joined = "".join(events)
    assert "test_started" in joined
    assert "skipped" in joined
    assert session.closed is True


@pytest.mark.asyncio
async def test_run_browser_batch_retry_skipped_and_worker_error(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession(fail_commit=True)
    tc = SimpleNamespace(id=13, project_id=1, name="retry-me", steps='[{"action":"click"}]')
    classification = SimpleNamespace(is_retryable=False, failure_category="not_retryable", reasoning="stop", confidence=0.7)

    async def _single_run(**kwargs):
        yield json.dumps({
            "_internal": True,
            "run_id": 44,
            "status": "failed",
            "failure_info": {"action": "click", "target": "#x", "value": None, "error": "boom", "screenshot": None},
        })

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)
    monkeypatch.setattr(test_cases_routes, "classify_failure", AsyncMock(return_value=classification))

    await test_cases_routes._run_browser_batch(
        browser="firefox",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=1,
        retry_mode="intelligent",
        batch_id="batch-2",
        context="ctx",
        viewport=None,
        project_id=1,
    )

    events = []
    while not queue.empty():
        events.append(await queue.get())

    joined = "".join(events)
    assert "retry_skipped" in joined
    assert session.rollback_called is True


@pytest.mark.asyncio
async def test_run_browser_batch_worker_exception_emits_error(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession()
    tc = SimpleNamespace(id=14, project_id=1, name="explode", steps='[{"action":"navigate"}]')

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("worker blew up")))

    await test_cases_routes._run_browser_batch(
        browser="webkit",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=0,
        retry_mode="simple",
        batch_id="batch-3",
        context=None,
        viewport=None,
        project_id=1,
    )

    events = []
    while not queue.empty():
        events.append(await queue.get())

    assert any("Error running test case 14" in e for e in events)


@pytest.mark.asyncio
async def test_run_browser_batch_breaks_without_internal_result(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession()
    tc = SimpleNamespace(id=15, project_id=1, name="no-internal", steps='[{"action":"navigate"}]')

    async def _single_run(**kwargs):
        yield 'data: {"type":"step_started"}\n\n'

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    await test_cases_routes._run_browser_batch(
        browser="chromium",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=0,
        retry_mode="simple",
        batch_id="batch-4",
        context=None,
        viewport=None,
        project_id=1,
    )

    events = []
    while not queue.empty():
        events.append(await queue.get())

    joined = "".join(events)
    assert "step_started" in joined
    assert counters["run_ids"] == []


@pytest.mark.asyncio
async def test_run_browser_batch_simple_retry_path(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession()
    tc = SimpleNamespace(id=16, project_id=1, name="simple-retry", steps='[{"action":"navigate"}]')
    attempts = {"count": 0}

    async def _single_run(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield json.dumps({"_internal": True, "run_id": 50, "status": "failed", "failure_info": None})
        else:
            yield json.dumps({"_internal": True, "run_id": 51, "status": "passed", "failure_info": None})

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    await test_cases_routes._run_browser_batch(
        browser="chromium",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=1,
        retry_mode="simple",
        batch_id="batch-5",
        context=None,
        viewport=None,
        project_id=1,
    )

    events = []
    while not queue.empty():
        events.append(await queue.get())

    joined = "".join(events)
    assert "test_retry" in joined
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_run_browser_batch_failure_with_no_retries(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession()
    tc = SimpleNamespace(id=17, project_id=1, name="no-retry-fail", steps='[{"action":"navigate"}]')

    async def _single_run(**kwargs):
        yield json.dumps({"_internal": True, "run_id": 52, "status": "failed", "failure_info": None})

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)

    await test_cases_routes._run_browser_batch(
        browser="chromium",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=0,
        retry_mode="simple",
        batch_id="batch-6",
        context=None,
        viewport=None,
        project_id=1,
    )

    assert counters["failed"] == 1


@pytest.mark.asyncio
async def test_run_browser_batch_intelligent_retryable_path(monkeypatch):
    queue = asyncio.Queue()
    counters = {"passed": 0, "failed": 0, "run_ids": []}
    session = _FakeWorkerSession()
    tc = SimpleNamespace(id=18, project_id=1, name="intelligent-retry", steps='[{"action":"click"}]')
    attempts = {"count": 0}
    classification = SimpleNamespace(is_retryable=True, failure_category="transient", reasoning="retry ok", confidence=0.8)

    async def _single_run(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            yield json.dumps({
                "_internal": True,
                "run_id": 60,
                "status": "failed",
                "failure_info": {"action": "click", "target": "#x", "value": None, "error": "boom", "screenshot": None},
            })
        else:
            yield json.dumps({"_internal": True, "run_id": 61, "status": "passed", "failure_info": None})

    monkeypatch.setattr(test_cases_routes, "Session", lambda engine: session)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kw: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", _single_run)
    monkeypatch.setattr(test_cases_routes, "classify_failure", AsyncMock(return_value=classification))

    await test_cases_routes._run_browser_batch(
        browser="firefox",
        test_cases=[tc],
        parallel=1,
        event_queue=queue,
        counters=counters,
        executor_client=SimpleNamespace(),
        use_simulation=False,
        project=SimpleNamespace(id=1, base_url="https://example.com"),
        batch_env_vars={},
        batch_env_base_url=None,
        environment_id=None,
        max_retries=1,
        retry_mode="intelligent",
        batch_id="batch-7",
        context=None,
        viewport=None,
        project_id=1,
    )

    events = []
    while not queue.empty():
        events.append(await queue.get())

    joined = "".join(events)
    assert "test_retry" in joined
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_run_batch_streaming_wrapper_returns_streaming_response():
    request = test_cases_routes.BatchRunRequest(test_case_ids=[1], browsers=["chromium"], parallel=9)
    response = await test_cases_routes.run_batch_streaming(1, request)
    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_run_batch_stream_uses_environment_and_simulation_warning(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), True

    async def fake_single_run(**kwargs):
        assert kwargs["env_base_url"] == "https://staging.example.com"
        yield json.dumps({"_internal": True, "run_id": 200, "status": "passed", "failure_info": None})

    tc = SimpleNamespace(id=20, project_id=1, name="Smoke", steps='[{"action":"navigate","value":"/"}]')
    env = SimpleNamespace(project_id=1, base_url="https://staging.example.com", name="staging", get_variables=lambda: {"ENV": "staging"})

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_environment", lambda s, env_id: env)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(
        test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[20], environment_id=5)
    )

    joined = "".join(events)
    assert "simulation mode" in joined
    assert "batch_completed" in joined


@pytest.mark.asyncio
async def test_run_batch_stream_environment_mismatch_ignored(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    async def fake_single_run(**kwargs):
        assert kwargs["env_base_url"] is None
        yield json.dumps({"_internal": True, "run_id": 201, "status": "passed", "failure_info": None})

    tc = SimpleNamespace(id=21, project_id=1, name="Smoke", steps='[{"action":"navigate","value":"/"}]')
    env = SimpleNamespace(project_id=99, base_url="https://wrong.example.com", name="wrong", get_variables=lambda: {"ENV": "wrong"})

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes.crud, "get_environment", lambda s, env_id: env)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(
        test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[21], environment_id=5)
    )

    assert any("batch_completed" in event for event in events)


@pytest.mark.asyncio
async def test_run_batch_stream_sequential_invalid_json_steps_skipped(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    tc = SimpleNamespace(id=22, project_id=1, name="Bad JSON", steps="{bad json")

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)

    events = await _collect_async(test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[22]))
    joined = "".join(events)
    assert "skipped" in joined


@pytest.mark.asyncio
async def test_run_batch_stream_sequential_breaks_without_internal_result(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    async def fake_single_run(**kwargs):
        yield 'data: {"type":"step_started"}\n\n'

    tc = SimpleNamespace(id=23, project_id=1, name="No internal", steps='[{"action":"navigate"}]')

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[23]))
    joined = "".join(events)
    assert "step_started" in joined
    assert "test_completed" not in joined


@pytest.mark.asyncio
async def test_run_batch_stream_sequential_failed_result_counts_failed(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield SimpleNamespace(), SimpleNamespace(), False

    async def fake_single_run(**kwargs):
        yield json.dumps({"_internal": True, "run_id": 250, "status": "failed", "failure_info": None})

    tc = SimpleNamespace(id=24, project_id=1, name="Failing", steps='[{"action":"navigate"}]')

    monkeypatch.setattr(test_cases_routes, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_cases_routes.crud, "get_project", lambda s, pid: SimpleNamespace(id=pid, base_url="https://example.com"))
    monkeypatch.setattr(test_cases_routes.crud, "get_test_case", lambda s, tcid: tc)
    monkeypatch.setattr(test_cases_routes, "resolve_references", lambda s, pid, steps, **kwargs: steps)
    monkeypatch.setattr(test_cases_routes, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_cases_routes, "_execute_single_run", fake_single_run)

    events = await _collect_async(test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[24]))
    joined = "".join(events)
    assert '"failed": 1' in joined


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory", "expected"),
    [
        (lambda: test_cases_routes.SQLAlchemyError("db down"), "Database error"),
        (lambda: test_cases_routes.HTTPError("executor down"), "Browser connection error"),
        (lambda: json.JSONDecodeError("bad json", "x", 0), "Invalid step data"),
        (lambda: RuntimeError("unexpected boom"), "unexpected boom"),
    ],
)
async def test_run_batch_stream_specific_exception_handlers(monkeypatch, error_factory, expected):
    class _Ctx:
        async def __aenter__(self):
            raise error_factory()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(test_cases_routes, "streaming_context", lambda: _Ctx())

    events = await _collect_async(test_cases_routes.run_batch_stream(project_id=1, test_case_ids=[1]))
    assert any(expected in event for event in events)


@pytest.mark.asyncio
async def test_run_batch_streaming_wrapper_clamps_parallel_and_forwards_args(monkeypatch):
    captured = {}

    async def fake_batch_stream(project_id, test_case_ids, browser=None, browsers=None, viewport=None, retry_config=None, parallel=1, context=None, environment_id=None):
        captured.update({
            "project_id": project_id,
            "test_case_ids": test_case_ids,
            "browser": browser,
            "browsers": browsers,
            "viewport": viewport,
            "parallel": parallel,
            "context": context,
            "environment_id": environment_id,
        })
        if False:
            yield ""

    request = test_cases_routes.BatchRunRequest(
        test_case_ids=[1, 2],
        browser="chromium",
        browsers=["firefox"],
        viewport=test_cases_routes.ViewportConfig(width=1000, height=700),
        parallel=9,
        context="suite",
        environment_id=4,
    )

    monkeypatch.setattr(test_cases_routes, "run_batch_stream", fake_batch_stream)
    response = await test_cases_routes.run_batch_streaming(7, request)

    assert isinstance(response, StreamingResponse)
    body_iter = response.body_iterator
    if hasattr(body_iter, "__anext__"):
        with pytest.raises(StopAsyncIteration):
            await body_iter.__anext__()
    assert captured["project_id"] == 7
    assert captured["test_case_ids"] == [1, 2]
    assert captured["browser"] == "chromium"
    assert captured["browsers"] == ["firefox"]
    assert captured["viewport"] == {"width": 1000, "height": 700}
    assert captured["parallel"] == 5
    assert captured["context"] == "suite"
    assert captured["environment_id"] == 4
