"""Helper and streaming tests for api/routes/test_runs.py"""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import httpx
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import StreamingResponse

import api.routes.test_runs as test_runs


class _StepReq:
    def __init__(self, action, description, target=None, value=None):
        self.action = action
        self.description = description
        self.target = target
        self.value = value

    def model_dump(self):
        return {
            "action": self.action,
            "description": self.description,
            "target": self.target,
            "value": self.value,
        }


def _fixture(name="setup", scope="global", fixture_id=1, steps=None, ttl=60):
    return SimpleNamespace(
        id=fixture_id,
        name=name,
        scope=scope,
        cache_ttl_seconds=ttl,
        get_setup_steps=lambda: steps if steps is not None else [{"action": "navigate", "value": "/login"}],
    )


@pytest.mark.asyncio
async def test_execute_steps_stream_project_not_found(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield object(), object(), True

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: None)

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go")]):
        events.append(ev)

    assert len(events) == 1
    assert "Project not found" in events[0]


@pytest.mark.asyncio
async def test_execute_steps_stream_simulation_success(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield object(), object(), True

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=123))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)

    events = []
    async for ev in test_runs.execute_steps_stream(
        1,
        [
            _StepReq("navigate", "Go home", value="/"),
            _StepReq("click", "Click submit", target="#submit"),
        ],
    ):
        events.append(ev)

    joined = "".join(events)
    assert "run_started" in joined
    assert "step_started" in joined
    assert "step_completed" in joined
    assert "run_completed" in joined


@pytest.mark.asyncio
async def test_execute_steps_stream_handles_sqlalchemy_error(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        raise SQLAlchemyError("db down")
        yield

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go")]):
        events.append(ev)

    assert len(events) == 1
    assert "Database error" in events[0]


def test_get_fixture_steps_by_ids_empty(monkeypatch):
    resolved, display, cached = test_runs._get_fixture_steps_by_ids(object(), [], 1, "chromium-headless")
    assert resolved == []
    assert display == []
    assert cached is False


def test_get_fixture_steps_by_ids_no_fixtures_found(monkeypatch):
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [])

    resolved, display, cached = test_runs._get_fixture_steps_by_ids(object(), [99], 1, "chromium-headless")

    assert resolved == []
    assert display == []
    assert cached is False


def test_get_fixture_steps_by_ids_cached_hit(monkeypatch):
    fixture = _fixture(name="login", scope="cached", fixture_id=5)
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fixture])
    monkeypatch.setattr(test_runs.crud, "get_valid_fixture_state", lambda s, fid, browser: object())
    monkeypatch.setattr(
        test_runs.crud,
        "get_decrypted_fixture_state",
        lambda s, state: {"url": "https://example.com", "cookies": []},
    )

    resolved, display, cached = test_runs._get_fixture_steps_by_ids(object(), [5], 1, "chromium-headless")

    assert cached is True
    assert resolved[0]["action"] == "restore_state"
    assert "cached browser state" in display[0]["value"]


def test_get_fixture_steps_by_ids_cache_miss_adds_capture(monkeypatch):
    fixture = _fixture(name="login", scope="cached", fixture_id=5, steps=[{"action": "navigate", "value": "/"}])
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fixture])
    monkeypatch.setattr(test_runs.crud, "get_valid_fixture_state", lambda s, fid, browser: None)
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)

    resolved, display, cached = test_runs._get_fixture_steps_by_ids(object(), [5], 1, "chromium-headless")

    assert cached is False
    assert resolved[-1]["action"] == "capture_state"
    assert display[-1]["action"] == "capture_state"


def test_get_fixture_steps_by_ids_non_cached_fixture_does_not_add_capture(monkeypatch):
    fixture = _fixture(name="regular", scope="test", fixture_id=8, steps=[{"action": "click", "target": "#a"}])
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fixture])
    monkeypatch.setattr(test_runs.crud, "get_valid_fixture_state", lambda s, fid, browser: None)
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)

    resolved, display, cached = test_runs._get_fixture_steps_by_ids(object(), [8], 1, "chromium-headless")

    assert cached is False
    assert len(resolved) == 1
    assert all(step.get("action") != "capture_state" for step in resolved)
    assert len(display) == 1


def test_get_fixture_steps_by_ids_empty_setup_steps(monkeypatch):
    fixture = _fixture(name="empty", scope="cached", fixture_id=10, steps=[])
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fixture])
    monkeypatch.setattr(test_runs.crud, "get_valid_fixture_state", lambda s, fid, browser: None)

    resolved, display, cached = test_runs._get_fixture_steps_by_ids(object(), [10], 1, "chromium-headless")

    assert resolved == []
    assert display == []
    assert cached is False


@pytest.mark.asyncio
async def test_execute_steps_stream_executor_path_success(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            yield {"type": "step_started", "step_number": 1}
            yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 12}
            yield {"type": "completed", "status": "passed"}

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=200))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go", value="/")]):
        events.append(ev)

    joined = "".join(events)
    assert "run_started" in joined
    assert "step_started" in joined
    assert "step_completed" in joined
    assert "run_completed" in joined


@pytest.mark.asyncio
async def test_execute_steps_stream_executor_error_event(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            yield {"type": "error", "error": "executor crashed"}

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=201))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go", value="/")]):
        events.append(ev)

    joined = "".join(events)
    assert "executor crashed" in joined


@pytest.mark.asyncio
async def test_execute_steps_stream_with_fixture_prepend_and_explicit_browser(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            yield {"type": "step_started", "step_number": 1}
            yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 12}

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(
        test_runs,
        "_get_fixture_steps_by_ids",
        lambda s, ids, pid, browser: (
            [{"action": "navigate", "value": "/setup", "fixture_name": "fx"}],
            [{"action": "navigate", "value": "/setup", "fixture_name": "fx"}],
            False,
        ),
    )
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=210))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)

    events = []
    async for ev in test_runs.execute_steps_stream(
        1,
        [_StepReq("click", "Click", target="#a")],
        browser="chrome",
        fixture_ids=[5],
    ):
        events.append(ev)

    joined = "".join(events)
    assert "run_started" in joined
    assert "run_completed" in joined


@pytest.mark.asyncio
async def test_execute_steps_stream_capture_state_cache_save_and_failure(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            yield {
                "type": "step_completed",
                "step_number": 3,
                "status": "passed",
                "duration": 11,
                "result": {"url": "https://example.com/app", "state": {"cookies": []}},
            }
            yield {
                "type": "step_completed",
                "step_number": 4,
                "status": "failed",
                "duration": 9,
                "error": "boom",
            }
            yield {"type": "completed", "status": "failed"}

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    fx_ok = _fixture(name="cached-ok", scope="cached", fixture_id=1, ttl=120)
    fx_err = _fixture(name="cached-err", scope="cached", fixture_id=2, ttl=120)

    def _delete_state(_session, fixture_id):
        if fixture_id == 2:
            raise RuntimeError("delete failed")
        return 1

    created_states = []

    def _create_state(**kwargs):
        created_states.append(kwargs)

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=211))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fx_ok, fx_err])
    monkeypatch.setattr(test_runs.crud, "get_valid_fixture_state", lambda s, fid, browser: None)
    monkeypatch.setattr(test_runs.crud, "delete_fixture_states_by_fixture", _delete_state)
    monkeypatch.setattr(test_runs.crud, "create_fixture_state", _create_state)

    steps = [
        _StepReq("capture_state", "capture"),
        _StepReq("click", "click", target="#submit"),
    ]

    events = []
    async for ev in test_runs.execute_steps_stream(1, steps, fixture_ids=[1, 2]):
        events.append(ev)

    joined = "".join(events)
    assert "run_completed" in joined
    assert "failed" in joined
    assert len(created_states) == 1
    assert created_states[0]["fixture_id"] == 1


@pytest.mark.asyncio
async def test_execute_steps_stream_handles_json_decode_error(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield object(), object(), False

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(
        test_runs,
        "resolve_references",
        lambda s, pid, steps: (_ for _ in ()).throw(json.JSONDecodeError("bad", "{", 0)),
    )

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go")]):
        events.append(ev)

    assert len(events) == 1
    assert "Invalid step data" in events[0]


@pytest.mark.asyncio
async def test_execute_steps_stream_handles_unexpected_error(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        yield object(), object(), False

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(
        test_runs,
        "resolve_references",
        lambda s, pid, steps: (_ for _ in ()).throw(RuntimeError("unexpected boom")),
    )

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go")]):
        events.append(ev)

    assert len(events) == 1
    assert "unexpected boom" in events[0]


@pytest.mark.asyncio
async def test_execute_steps_stream_capture_state_skips_invalid_result_shapes(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            # capture_state with non-dict result -> skips cache persistence path
            yield {
                "type": "step_completed",
                "step_number": 3,
                "status": "passed",
                "duration": 7,
                "result": "not-a-dict",
            }
            # capture_state with dict missing state -> skips cache persistence path
            yield {
                "type": "step_completed",
                "step_number": 3,
                "status": "passed",
                "duration": 7,
                "result": {"url": "https://example.com/app"},
            }
            yield {"type": "completed", "status": "passed"}

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    # One cached and one non-cached fixture to cover the fixture.scope guard branch.
    fx_cached = _fixture(name="cached", scope="cached", fixture_id=1, ttl=120)
    fx_regular = _fixture(name="regular", scope="test", fixture_id=3, ttl=120)

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=212))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fx_cached, fx_regular])
    monkeypatch.setattr(test_runs.crud, "get_valid_fixture_state", lambda s, fid, browser: None)

    create_state_calls = []
    monkeypatch.setattr(test_runs.crud, "create_fixture_state", lambda **kwargs: create_state_calls.append(kwargs))
    monkeypatch.setattr(test_runs.crud, "delete_fixture_states_by_fixture", lambda s, fid: 1)

    steps = [
        _StepReq("capture_state", "capture"),
    ]
    events = []
    async for ev in test_runs.execute_steps_stream(1, steps, fixture_ids=[1, 3]):
        events.append(ev)

    assert len(create_state_calls) == 0
    assert any("run_completed" in e for e in events)


@pytest.mark.asyncio
async def test_execute_steps_streaming_returns_streaming_response_wrapper():
    req = test_runs.ExecuteRequest(
        project_id=1,
        steps=[test_runs.ExecuteStepRequest(action="navigate", description="go")],
        browser="chromium",
        fixture_ids=[1],
    )

    resp = await test_runs.execute_steps_streaming(req)
    assert isinstance(resp, StreamingResponse)


@pytest.mark.asyncio
async def test_execute_steps_stream_capture_state_non_cached_fixture_skips_persist(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            yield {
                "type": "step_completed",
                "step_number": 1,
                "status": "passed",
                "duration": 7,
                "result": {"url": "https://example.com/app", "state": {"cookies": []}},
            }

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    fx_regular = _fixture(name="regular", scope="test", fixture_id=3, ttl=120)

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=213))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)
    monkeypatch.setattr(test_runs.crud, "get_fixtures_by_ids", lambda s, ids: [fx_regular])

    persist_calls = []
    monkeypatch.setattr(test_runs.crud, "delete_fixture_states_by_fixture", lambda s, fid: persist_calls.append(("del", fid)))
    monkeypatch.setattr(test_runs.crud, "create_fixture_state", lambda **kwargs: persist_calls.append(("create", kwargs.get("fixture_id"))))

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("capture_state", "capture")], fixture_ids=[3]):
        events.append(ev)

    assert any("run_completed" in e for e in events)
    assert persist_calls == []


@pytest.mark.asyncio
async def test_execute_steps_stream_completed_event_does_not_stop_loop(monkeypatch):
    class _ExecutorClient:
        async def execute_stream(self, **kwargs):
            yield {"type": "completed", "status": "passed"}
            yield {"type": "step_started", "step_number": 1}
            yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 3}

    @asynccontextmanager
    async def fake_ctx():
        yield object(), _ExecutorClient(), False

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)
    monkeypatch.setattr(test_runs.crud, "get_project", lambda s, pid: SimpleNamespace(base_url="https://example.com"))
    monkeypatch.setattr(test_runs, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(test_runs, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(test_runs.crud, "create_test_run", lambda s, req: SimpleNamespace(id=214))
    monkeypatch.setattr(test_runs.crud, "update_test_run", lambda s, rid, data: None)
    monkeypatch.setattr(test_runs.crud, "create_test_run_step", lambda s, step: None)

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "go", value="/")]):
        events.append(ev)

    joined = "".join(events)
    assert "step_started" in joined
    assert "step_completed" in joined


@pytest.mark.asyncio
async def test_execute_steps_stream_handles_http_error(monkeypatch):
    @asynccontextmanager
    async def fake_ctx():
        raise httpx.HTTPError("net down")
        yield

    monkeypatch.setattr(test_runs, "streaming_context", fake_ctx)

    events = []
    async for ev in test_runs.execute_steps_stream(1, [_StepReq("navigate", "Go")]):
        events.append(ev)

    assert len(events) == 1
    assert "Browser connection error" in events[0]
