import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.routes import recorder


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise recorder.httpx.HTTPError("http error")

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, post_response=None, get_response=None):
        self._post_response = post_response or _FakeResponse()
        self._get_response = get_response or _FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self._post_response

    async def get(self, *args, **kwargs):
        return self._get_response


def _clear_recorder_state():
    recorder._active_sessions.clear()
    recorder._active_processors.clear()


def test_start_status_and_stop_recording_flow(client, monkeypatch):
    _clear_recorder_state()

    monkeypatch.setattr(
        recorder.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(
            post_response=_FakeResponse(payload={"session_id": "sess-1"})
        ),
    )

    start = client.post(
        "/api/projects/101/recorder/start",
        json={"base_url": "https://example.com", "viewport_width": 1200, "viewport_height": 800},
    )
    assert start.status_code == 200
    assert start.json()["session_id"] == "sess-1"

    status_active = client.get("/api/projects/101/recorder/status")
    assert status_active.status_code == 200
    assert status_active.json()["active"] is True

    stop = client.post("/api/projects/101/recorder/stop")
    assert stop.status_code == 200
    assert stop.json()["session_id"] == "sess-1"

    status_inactive = client.get("/api/projects/101/recorder/status")
    assert status_inactive.status_code == 200
    assert status_inactive.json()["active"] is False


def test_start_recording_conflict_and_stop_without_session(client, monkeypatch):
    _clear_recorder_state()

    monkeypatch.setattr(
        recorder.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(
            post_response=_FakeResponse(payload={"session_id": "sess-2"})
        ),
    )

    first = client.post(
        "/api/projects/102/recorder/start",
        json={"base_url": "https://example.com", "viewport_width": 1280, "viewport_height": 720},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/projects/102/recorder/start",
        json={"base_url": "https://example.com", "viewport_width": 1280, "viewport_height": 720},
    )
    assert second.status_code == 409

    _clear_recorder_state()
    stop_missing = client.post("/api/projects/999/recorder/stop")
    assert stop_missing.status_code == 404


def test_stop_recording_reprocesses_raw_events_when_ws_steps_empty(client, monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[103] = "sess-raw"
    recorder._active_processors[103] = recorder.RecorderEventProcessor(base_url="https://example.com")

    raw_events = [
        {"type": "navigate", "url": "https://example.com/login", "timestamp": 1000},
        {
            "type": "click",
            "tag": "BUTTON",
            "text": "Sign in",
            "selector": "button.signin",
            "timestamp": 1200,
        },
    ]

    monkeypatch.setattr(
        recorder.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(
            post_response=_FakeResponse(payload={"events": raw_events})
        ),
    )

    stop = client.post("/api/projects/103/recorder/stop")
    assert stop.status_code == 200
    assert stop.json()["step_count"] >= 1


def test_generate_metadata_empty_steps_returns_400(client):
    _clear_recorder_state()
    res = client.post("/api/projects/201/recorder/generate-metadata", json={"steps": [], "base_url": ""})
    assert res.status_code == 400


def test_generate_metadata_fallback_when_llm_fails(client, monkeypatch):
    _clear_recorder_state()

    monkeypatch.setattr(recorder, "get_llm", lambda tier: (_ for _ in ()).throw(RuntimeError("llm down")))

    res = client.post(
        "/api/projects/202/recorder/generate-metadata",
        json={
            "base_url": "https://example.com",
            "steps": [
                {
                    "action": "click",
                    "target": "Login",
                    "value": None,
                    "description": "Click login",
                    "is_credential": False,
                    "coordinates": None,
                    "locators": None,
                    "causes_navigation": False,
                }
            ],
        },
    )
    assert res.status_code == 200
    assert "Recorded Test" in res.json()["name"]


def test_refine_steps_fallback_when_llm_fails(client, monkeypatch):
    _clear_recorder_state()

    monkeypatch.setattr(recorder, "get_llm", lambda tier: (_ for _ in ()).throw(RuntimeError("llm down")))

    payload = {
        "base_url": "https://example.com",
        "steps": [
            {
                "action": "navigate",
                "target": None,
                "value": "/",
                "description": "Go home",
                "is_credential": False,
                "coordinates": {"x": 1, "y": 2},
                "locators": {"css": "body"},
                "causes_navigation": False,
            }
        ],
    }

    res = client.post("/api/projects/203/recorder/refine-steps", json=payload)
    assert res.status_code == 200
    assert len(res.json()["steps"]) == 1
    assert res.json()["steps"][0]["action"] == "navigate"


def test_start_recording_executor_httpx_error_returns_502(client, monkeypatch):
    """start_recording returns 502 when the executor raises httpx.HTTPError."""
    _clear_recorder_state()

    class _BrokenClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs):
            raise recorder.httpx.ConnectError("connection refused")

    monkeypatch.setattr(recorder.httpx, "AsyncClient", lambda timeout=30.0: _BrokenClient())

    res = client.post(
        "/api/projects/301/recorder/start",
        json={"base_url": "https://example.com"},
    )
    assert res.status_code == 502
    assert "unreachable" in res.json()["detail"].lower()
    _clear_recorder_state()


def test_refine_steps_empty_steps_returns_400(client):
    """refine_steps returns 400 when no steps provided."""
    _clear_recorder_state()
    res = client.post(
        "/api/projects/302/recorder/refine-steps",
        json={"steps": [], "base_url": "https://example.com"},
    )
    assert res.status_code == 400
    assert "No steps provided" in res.json()["detail"]


def test_generate_metadata_success_path(client, monkeypatch):
    """generate_metadata success path — AI chain runs and returns GeneratedMetadata."""
    _clear_recorder_state()

    # Mock fake chain that returns a real GeneratedMetadata object
    from api.routes.recorder import GeneratedMetadata

    class _FakeChain:
        async def ainvoke(self, *args, **kwargs):
            return GeneratedMetadata(
                name="Login Flow Test",
                description="Tests the login workflow",
                priority="critical",
                tags=["auth", "smoke"],
            )

    class _FakeStructuredModel:
        def __init__(self): pass

    class _FakeLLM:
        def with_structured_output(self, cls):
            return _FakeStructuredModel()

    class _FakePrompt:
        def __or__(self, other):
            return _FakeChain()

    monkeypatch.setattr(recorder, "get_llm", lambda tier="default": _FakeLLM())
    monkeypatch.setattr(recorder, "METADATA_PROMPT", _FakePrompt())

    res = client.post(
        "/api/projects/400/recorder/generate-metadata",
        json={
            "base_url": "https://example.com",
            "steps": [
                {
                    "action": "navigate",
                    "target": None,
                    "value": "/login",
                    "description": "Go to login",
                    "is_credential": False,
                    "coordinates": None,
                    "locators": None,
                    "causes_navigation": False,
                },
                {
                    "action": "type",
                    "target": "password",
                    "value": "{{password}}",
                    "description": "Enter password",
                    "is_credential": True,
                    "coordinates": None,
                    "locators": None,
                    "causes_navigation": False,
                },
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Login Flow Test"
    assert data["priority"] == "critical"
    assert "auth" in data["tags"]


def test_refine_steps_success_path(client, monkeypatch):
    """refine_steps success path — AI chain runs and returns RefinedStepsResponse."""
    _clear_recorder_state()

    from api.routes.recorder import RefinedStepsResponse, RefinedStep

    class _FakeChain:
        async def ainvoke(self, *args, **kwargs):
            return RefinedStepsResponse(steps=[
                RefinedStep(
                    action="navigate",
                    target=None,
                    value="/dashboard",
                    description="Go to dashboard",
                ),
                RefinedStep(
                    action="click",
                    target="Save button",
                    value=None,
                    description="Click Save",
                ),
            ])

    class _FakeStructuredModel:
        def __init__(self): pass

    class _FakeLLM:
        def with_structured_output(self, cls):
            return _FakeStructuredModel()

    class _FakePrompt:
        def __or__(self, other):
            return _FakeChain()

    monkeypatch.setattr(recorder, "get_llm", lambda tier="default": _FakeLLM())
    monkeypatch.setattr(recorder, "REFINE_PROMPT", _FakePrompt())

    res = client.post(
        "/api/projects/401/recorder/refine-steps",
        json={
            "base_url": "https://example.com",
            "steps": [
                {
                    "action": "navigate",
                    "target": None,
                    "value": "/dashboard",
                    "description": "Navigate",
                    "is_credential": False,
                    "coordinates": None,
                    "locators": None,
                    "causes_navigation": False,
                },
                {
                    "action": "click",
                    "target": "#save-btn",
                    "value": None,
                    "description": "Click",
                    "is_credential": False,
                    "coordinates": {"x": 100, "y": 200},
                    "locators": {"css": "#save-btn"},
                    "causes_navigation": False,
                },
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "steps" in data
    assert len(data["steps"]) == 2
    assert data["steps"][0]["action"] == "navigate"


def test_scope_dropdown_assertions_and_restore_metadata_helpers():
    scoped = recorder._scope_dropdown_assertions(
        [
            {"action": "click", "target": "[data-testid=\"status-trigger-1\"]", "value": None},
            {"action": "click", "target": "Mark as Ready", "value": None},
            {"action": "assert_text", "target": None, "value": "Ready"},
        ]
    )
    assert scoped[2]["action"] == "assert_element"
    assert ':has-text("Ready")' in scoped[2]["target"]

    original = [
        recorder.RecordedStepInput(
            action="click",
            target="#submit-btn",
            value=None,
            description="",
            coordinates={"x": 10, "y": 20},
            locators={"css": "#submit-btn"},
        )
    ]
    restored = recorder._restore_metadata(
        [{"action": "click", "target": "#submit-btn", "value": None, "description": "Click submit"}],
        original,
    )
    assert restored[0]["target"] == "#submit-btn"
    assert restored[0]["coordinates"] == {"x": 10, "y": 20}


def test_stop_recording_handles_non_http_json_parse_error(client, monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[777] = "sess-json-error"
    recorder._active_processors[777] = recorder.RecorderEventProcessor(base_url="https://example.com")

    class _BadJsonResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(
        recorder.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(post_response=_BadJsonResponse()),
    )

    res = client.post("/api/projects/777/recorder/stop")
    assert res.status_code == 200
    assert res.json()["step_count"] == 0


def test_stop_recording_handles_executor_http_error(client, monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[776] = "sess-stop-http-error"
    recorder._active_processors[776] = recorder.RecorderEventProcessor(base_url="https://example.com")

    class _HttpErrorResponse:
        def raise_for_status(self):
            raise recorder.httpx.HTTPError("executor stop failed")

        def json(self):
            return {"events": []}

    monkeypatch.setattr(
        recorder.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(post_response=_HttpErrorResponse()),
    )

    res = client.post("/api/projects/776/recorder/stop")
    assert res.status_code == 200
    assert res.json()["session_id"] == "sess-stop-http-error"


def test_generate_metadata_without_description_branch(client, monkeypatch):
    _clear_recorder_state()

    monkeypatch.setattr(recorder, "get_llm", lambda tier: (_ for _ in ()).throw(RuntimeError("llm down")))

    res = client.post(
        "/api/projects/778/recorder/generate-metadata",
        json={
            "base_url": "https://example.com",
            "steps": [
                {
                    "action": "click",
                    "target": "Submit",
                    "value": None,
                    "description": "",
                    "is_credential": False,
                    "coordinates": None,
                    "locators": None,
                    "causes_navigation": False,
                }
            ],
        },
    )
    assert res.status_code == 200


def test_scope_dropdown_assertions_navigation_or_long_text_not_replaced():
    # If wait_for_page appears before menu click, we skip dropdown scoping.
    with_wait = recorder._scope_dropdown_assertions(
        [
            {"action": "click", "target": "#status-trigger", "value": None},
            {"action": "wait_for_page", "target": None, "value": "load"},
            {"action": "click", "target": "Ready", "value": None},
            {"action": "assert_text", "target": None, "value": "Ready"},
        ]
    )
    assert with_wait[3]["action"] == "assert_text"

    # If assert_text value is long, we keep assert_text as page-level assertion.
    long_value = "x" * 50
    long_text = recorder._scope_dropdown_assertions(
        [
            {"action": "click", "target": "#status-trigger", "value": None},
            {"action": "click", "target": "Ready", "value": None},
            {"action": "assert_text", "target": None, "value": long_value},
        ]
    )
    assert long_text[2]["action"] == "assert_text"


def test_scope_dropdown_assertions_no_assert_text_branch():
    result = recorder._scope_dropdown_assertions(
        [
            {"action": "click", "target": "#status-trigger", "value": None},
            {"action": "click", "target": "Ready", "value": None},
            {"action": "click", "target": "Other button", "value": None},
        ]
    )
    assert result[2]["action"] == "click"


def test_scope_dropdown_assertions_no_menuitem_found_branches():
    result = recorder._scope_dropdown_assertions(
        [
            {"action": "click", "target": "#status-trigger", "value": None},
            {"action": "wait", "target": "spinner", "value": None},
            {"action": "click", "target": "#still-css", "value": None},
            {"action": "assert_text", "target": None, "value": "Ready"},
        ]
    )
    assert result[3]["action"] == "assert_text"


def test_restore_metadata_duplicate_keys_and_used_index_guards():
    originals = [
        recorder.RecordedStepInput(
            action="click",
            target="#duplicate",
            value=None,
            description="",
            coordinates={"x": 1, "y": 1},
            locators={"css": "#duplicate"},
        ),
        recorder.RecordedStepInput(
            action="click",
            target="#duplicate",
            value=None,
            description="",
            coordinates={"x": 2, "y": 2},
            locators={"css": "#duplicate"},
        ),
        recorder.RecordedStepInput(
            action="type",
            target="Email",
            value="a@example.com",
            description="",
            coordinates={"x": 3, "y": 3},
            locators=None,
        ),
    ]

    refined = [
        {"action": "click", "target": "#duplicate", "value": None, "description": "first"},
        {"action": "click", "target": "#duplicate", "value": None, "description": "second"},
        {"action": "type", "target": "Email", "value": "a@example.com", "description": "third"},
        {"action": "type", "target": "Email", "value": "a@example.com", "description": "fourth"},
    ]

    out = recorder._restore_metadata(refined, originals)
    # CSS index keeps the last seen selector match when duplicates exist.
    assert out[0]["coordinates"] == {"x": 2, "y": 2}
    # Second duplicate click can still match the remaining original duplicate.
    assert out[1]["coordinates"] == {"x": 1, "y": 1}
    assert out[2]["coordinates"] == {"x": 3, "y": 3}
    assert "coordinates" not in out[3]


def test_restore_metadata_step_without_target_or_value():
    originals = [
        recorder.RecordedStepInput(
            action="screenshot",
            target=None,
            value=None,
            description="",
            coordinates=None,
            locators=None,
        )
    ]

    out = recorder._restore_metadata(
        [{"action": "screenshot", "target": None, "value": None, "description": "Snap"}],
        originals,
    )
    assert out[0]["action"] == "screenshot"


def test_restore_metadata_duplicate_action_value_index_guard():
    originals = [
        recorder.RecordedStepInput(
            action="type",
            target="Email",
            value="same@example.com",
            description="",
            coordinates={"x": 10, "y": 10},
            locators=None,
        ),
        recorder.RecordedStepInput(
            action="type",
            target="Alt Email",
            value="same@example.com",
            description="",
            coordinates={"x": 20, "y": 20},
            locators=None,
        ),
    ]

    out = recorder._restore_metadata(
        [{"action": "type", "target": None, "value": "same@example.com", "description": "Type email"}],
        originals,
    )

    assert out[0]["coordinates"] == {"x": 10, "y": 10}


def test_refine_steps_includes_credential_and_navigation_markers(client, monkeypatch):
    _clear_recorder_state()
    captured = {}

    from api.routes.recorder import RefinedStepsResponse, RefinedStep

    class _FakeChain:
        async def ainvoke(self, payload):
            captured["steps_text"] = payload["steps_text"]
            return RefinedStepsResponse(steps=[
                RefinedStep(action="navigate", target=None, value="/", description="Go home"),
            ])

    class _FakeStructuredModel:
        pass

    class _FakeLLM:
        def with_structured_output(self, cls):
            return _FakeStructuredModel()

    class _FakePrompt:
        def __or__(self, other):
            return _FakeChain()

    monkeypatch.setattr(recorder, "get_llm", lambda tier="default": _FakeLLM())
    monkeypatch.setattr(recorder, "REFINE_PROMPT", _FakePrompt())

    res = client.post(
        "/api/projects/779/recorder/refine-steps",
        json={
            "base_url": "https://example.com",
            "steps": [
                {
                    "action": "type",
                    "target": "Password",
                    "value": "secret",
                    "description": "",
                    "is_credential": True,
                    "coordinates": None,
                    "locators": None,
                    "causes_navigation": True,
                }
            ],
        },
    )
    assert res.status_code == 200
    assert "[CREDENTIAL]" in captured["steps_text"]
    assert "[CAUSES NAVIGATION]" in captured["steps_text"]
    assert "\u2014" not in captured["steps_text"]


class _FakeWSStep:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class _FakeProcessor:
    def __init__(self):
        self.steps = [_FakeWSStep({"action": "navigate", "value": "/"})]

    def process_event(self, _raw):
        self.steps.append(_FakeWSStep({"action": "click", "target": "button"}))


class _FakeWS:
    def __init__(self, command_payload=None, receive_exc=None, close_exc=None):
        self.sent = []
        self.closed = []
        self.accepted = False
        self._command_payload = command_payload or {"command": "stop"}
        self._receive_exc = receive_exc
        self._close_exc = close_exc

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if self._receive_exc:
            raise self._receive_exc
        return self._command_payload

    async def close(self, code=None, reason=None):
        self.closed.append((code, reason))
        if self._close_exc:
            raise self._close_exc


class _DummyTask:
    def __init__(self, coro):
        self.coro = coro
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def test_recorder_websocket_no_active_session_closes_4004():
    _clear_recorder_state()
    ws = _FakeWS()

    asyncio.run(recorder.recorder_websocket(ws, 880))

    assert ws.closed and ws.closed[0][0] == 4004
    assert ws.accepted is False


def test_recorder_websocket_stop_command_and_polling(monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[881] = "sess-ws"
    recorder._active_processors[881] = _FakeProcessor()
    ws = _FakeWS(command_payload={"command": "stop"})

    class _EventsResponse:
        status_code = 200

        def json(self):
            return {"events": [{"type": "click"}]}

    class _EventsClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _EventsResponse()

    monkeypatch.setattr(recorder.httpx, "AsyncClient", lambda: _EventsClient())

    async def _break_sleep(_):
        raise RuntimeError("stop poll loop in test")

    monkeypatch.setattr(recorder.asyncio, "sleep", _break_sleep)
    monkeypatch.setattr(recorder.asyncio, "create_task", lambda coro: _DummyTask(coro))

    async def _fake_wait(tasks, return_when=None):
        # Run poller once to cover poll/get/send path, then run receiver stop path.
        try:
            await tasks[0].coro
        except RuntimeError:
            pass
        await tasks[1].coro
        return ({tasks[1]}, {tasks[0]})

    monkeypatch.setattr(recorder.asyncio, "wait", _fake_wait)

    asyncio.run(recorder.recorder_websocket(ws, 881))

    assert ws.accepted is True
    assert any(m.get("type") == "step" for m in ws.sent)


def test_recorder_websocket_receive_disconnect_and_close_error(monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[882] = "sess-disconnect"
    recorder._active_processors[882] = _FakeProcessor()
    ws = _FakeWS(
        receive_exc=recorder.WebSocketDisconnect(),
        close_exc=RuntimeError("close failed"),
    )

    class _EventsResponse:
        status_code = 500

        def json(self):
            return {"events": []}

    class _EventsClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _EventsResponse()

    monkeypatch.setattr(recorder.httpx, "AsyncClient", lambda: _EventsClient())
    monkeypatch.setattr(recorder.asyncio, "create_task", lambda coro: _DummyTask(coro))

    async def _fake_wait(tasks, return_when=None):
        await tasks[1].coro
        tasks[0].coro.close()
        return ({tasks[1]}, {tasks[0]})

    monkeypatch.setattr(recorder.asyncio, "wait", _fake_wait)

    asyncio.run(recorder.recorder_websocket(ws, 882))
    assert ws.accepted is True


def test_recorder_websocket_creates_processor_and_exits_poll_loop_when_stopped(monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[883] = "sess-create-processor"
    ws = _FakeWS(command_payload={"command": "stop"})

    class _EventsClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("poll loop should not call get once stop flag is set")

    monkeypatch.setattr(recorder.httpx, "AsyncClient", lambda: _EventsClient())
    monkeypatch.setattr(recorder.asyncio, "create_task", lambda coro: _DummyTask(coro))

    async def _fake_wait(tasks, return_when=None):
        await tasks[1].coro
        await tasks[0].coro
        return ({tasks[1]}, {tasks[0]})

    monkeypatch.setattr(recorder.asyncio, "wait", _fake_wait)

    asyncio.run(recorder.recorder_websocket(ws, 883))

    assert ws.accepted is True
    assert 883 in recorder._active_processors


def test_recorder_websocket_non_stop_then_stop_and_non_200_poll(monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[884] = "sess-non-200"
    recorder._active_processors[884] = _FakeProcessor()

    class _SequenceWS(_FakeWS):
        def __init__(self):
            super().__init__()
            self._payloads = [{"command": "noop"}, {"command": "stop"}]

        async def receive_json(self):
            return self._payloads.pop(0)

    ws = _SequenceWS()

    class _EventsResponse:
        status_code = 500

        def json(self):
            return {"events": []}

    class _EventsClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _EventsResponse()

    async def _break_sleep(_):
        raise RuntimeError("end loop")

    monkeypatch.setattr(recorder.httpx, "AsyncClient", lambda: _EventsClient())
    monkeypatch.setattr(recorder.asyncio, "sleep", _break_sleep)
    monkeypatch.setattr(recorder.asyncio, "create_task", lambda coro: _DummyTask(coro))

    async def _fake_wait(tasks, return_when=None):
        try:
            await tasks[0].coro
        except RuntimeError:
            pass
        await tasks[1].coro
        return ({tasks[1]}, {tasks[0]})

    monkeypatch.setattr(recorder.asyncio, "wait", _fake_wait)

    asyncio.run(recorder.recorder_websocket(ws, 884))
    assert ws.accepted is True


def test_recorder_websocket_poll_exception_and_receive_exception(monkeypatch):
    _clear_recorder_state()

    recorder._active_sessions[885] = "sess-errors"
    recorder._active_processors[885] = _FakeProcessor()
    ws = _FakeWS(receive_exc=RuntimeError("frontend receive failed"))

    class _EventsClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise RuntimeError("poll failed")

    async def _break_sleep(_):
        raise RuntimeError("end loop")

    monkeypatch.setattr(recorder.httpx, "AsyncClient", lambda: _EventsClient())
    monkeypatch.setattr(recorder.asyncio, "sleep", _break_sleep)
    monkeypatch.setattr(recorder.asyncio, "create_task", lambda coro: _DummyTask(coro))

    async def _fake_wait(tasks, return_when=None):
        try:
            await tasks[0].coro
        except RuntimeError:
            pass
        await tasks[1].coro
        return ({tasks[1]}, {tasks[0]})

    monkeypatch.setattr(recorder.asyncio, "wait", _fake_wait)

    asyncio.run(recorder.recorder_websocket(ws, 885))
    assert ws.accepted is True
