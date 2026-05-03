from unittest.mock import AsyncMock

import pytest

from agent.executor_client import PlaywrightExecutorClient


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


@pytest.mark.asyncio
async def test_executor_client_health_check_and_browsers(monkeypatch):
    client = PlaywrightExecutorClient()
    try:
        client.client.get = AsyncMock(side_effect=[
            _FakeResponse(status_code=200, json_data={"status": "ok"}),
            _FakeResponse(status_code=200, json_data={"browsers": [{"id": "chromium"}], "default": "chromium"}),
        ])

        assert await client.health_check() is True
        browsers = await client.get_browsers()
        assert browsers["default"] == "chromium"
        assert browsers["browsers"][0]["id"] == "chromium"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_client_returns_error_event_on_stream_failure(monkeypatch):
    client = PlaywrightExecutorClient()
    try:
        class _Boom:
            def __call__(self, *args, **kwargs):
                raise RuntimeError("stream down")

        client.client.stream = _Boom()

        events = []
        async for event in client.execute_stream(base_url="https://example.com", steps=[]):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "stream down" in events[0]["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_client_health_check_non_ok_status(monkeypatch):
    client = PlaywrightExecutorClient()
    try:
        client.client.get = AsyncMock(return_value=_FakeResponse(status_code=503, json_data={"status": "down"}))
        assert await client.health_check() is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_client_get_browsers_non_200_returns_empty(monkeypatch):
    client = PlaywrightExecutorClient()
    try:
        client.client.get = AsyncMock(return_value=_FakeResponse(status_code=500, json_data={}))
        out = await client.get_browsers()
        assert out == {"browsers": [], "default": None}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_client_execute_stream_non_200_returns_error_event(monkeypatch):
    class _FakeStreamResponse:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_text(self):
            if False:
                yield ""

    class _FakeClient:
        def stream(self, *args, **kwargs):
            return _FakeStreamResponse()

    client = PlaywrightExecutorClient()
    client.client = _FakeClient()

    events = []
    async for event in client.execute_stream(base_url="https://example.com", steps=[]):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "Executor returned 500" in events[0]["error"]


@pytest.mark.asyncio
async def test_executor_client_execute_stream_parses_messages_and_remainder(monkeypatch):
    chunks = [
        'data: {"type":"step","n":1}\n\n',
        'data: {"type":"done"}',
    ]

    class _FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_text(self):
            for chunk in chunks:
                yield chunk

    class _FakeClient:
        def stream(self, *args, **kwargs):
            return _FakeStreamResponse()

    client = PlaywrightExecutorClient()
    client.client = _FakeClient()

    events = []
    async for event in client.execute_stream(base_url="https://example.com", steps=[]):
        events.append(event)

    assert events[0]["type"] == "step"
    assert events[1]["type"] == "done"


@pytest.mark.asyncio
async def test_executor_client_health_check_exception_returns_false():
    """Test health_check returns False when HTTP request raises exception."""
    client = PlaywrightExecutorClient()
    try:
        client.client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        result = await client.health_check()
        assert result is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_client_get_browsers_exception_returns_empty():
    """Test get_browsers returns empty when HTTP request raises exception."""
    client = PlaywrightExecutorClient()
    try:
        client.client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        result = await client.get_browsers()
        assert result == {"browsers": [], "default": None}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_client_stream_invalid_json_continues():
    """Test execute_stream skips lines with invalid JSON."""
    chunks = [
        'data: not-valid-json\n\ndata: {"type":"step"}\n\n',
    ]

    class _FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_text(self):
            for chunk in chunks:
                yield chunk

    class _FakeClient:
        def stream(self, *args, **kwargs):
            return _FakeStreamResponse()

    client = PlaywrightExecutorClient()
    client.client = _FakeClient()

    events = []
    async for event in client.execute_stream(base_url="https://example.com", steps=[]):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "step"
