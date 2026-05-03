from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from db.models import RunStatus
from scheduler import notifier


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = SimpleNamespace(url="http://example.com")
            raise notifier.httpx.HTTPStatusError("bad", request=request, response=self)


class _FakeAsyncClient:
    def __init__(self, response=None):
        self._response = response or _FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self._response


def _scheduled_run(status=RunStatus.PASSED):
    return SimpleNamespace(
        id=11,
        status=status,
        pass_count=3,
        fail_count=1,
        test_count=4,
        thread_id="th-1",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow() + timedelta(seconds=8),
    )


def _schedule():
    return SimpleNamespace(id=12, name="Nightly")


def _channel(channel_type="webhook", webhook_url="https://hooks.example.com", channel_id=13):
    return SimpleNamespace(
        id=channel_id,
        channel_type=channel_type,
        webhook_url=webhook_url,
        webhook_template=None,
    )


def test_render_template_and_context():
    context = notifier._get_template_context(_scheduled_run(RunStatus.PASSED), _schedule())
    rendered = notifier._render_template("{{schedule.name}} {{status}} {{duration}}", context)
    assert "Nightly" in rendered
    assert "passed" in rendered
    assert rendered.split()[-1].endswith("s")


@pytest.mark.asyncio
async def test_send_webhook_success(monkeypatch):
    monkeypatch.setattr(notifier.httpx, "AsyncClient", lambda timeout=30.0: _FakeAsyncClient())
    ok, err = await notifier.send_webhook(_channel(), _scheduled_run(), _schedule())
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_send_webhook_handles_bad_json_template():
    ch = _channel()
    ch.webhook_template = "{not-json"
    ok, err = await notifier.send_webhook(ch, _scheduled_run(), _schedule())
    assert ok is False
    assert "Invalid template JSON" in err


@pytest.mark.asyncio
async def test_send_notifications_mixed_channels(monkeypatch):
    async def fake_webhook(channel, scheduled_run, schedule):
        return (channel.channel_type != "slack", "boom" if channel.channel_type == "slack" else "")

    monkeypatch.setattr(notifier, "send_webhook", fake_webhook)

    sent, errors = await notifier.send_notifications(
        _scheduled_run(),
        _schedule(),
        [
            _channel("webhook", channel_id=101),
            _channel("slack", channel_id=102),
            _channel("email", channel_id=103),
        ],
    )

    assert len(sent) == 1
    assert len(errors) == 2


@pytest.mark.asyncio
async def test_send_webhook_no_url():
    """send_webhook returns (False, ...) when no webhook URL configured."""
    ch = _channel(webhook_url="")
    ok, err = await notifier.send_webhook(ch, _scheduled_run(), _schedule())
    assert ok is False
    assert "No webhook URL" in err


@pytest.mark.asyncio
async def test_send_webhook_http_status_error(monkeypatch):
    """send_webhook returns (False, error) on HTTPStatusError."""
    monkeypatch.setattr(
        notifier.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(_FakeResponse(status_code=500, text="Server Error")),
    )
    ok, err = await notifier.send_webhook(_channel(), _scheduled_run(), _schedule())
    assert ok is False
    assert "500" in err


@pytest.mark.asyncio
async def test_send_webhook_request_error(monkeypatch):
    """send_webhook returns (False, error) on RequestError (connection failure)."""
    class _BrokenClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs):
            raise notifier.httpx.ConnectError("connection refused")

    monkeypatch.setattr(notifier.httpx, "AsyncClient", lambda timeout=30.0: _BrokenClient())
    ok, err = await notifier.send_webhook(_channel(), _scheduled_run(), _schedule())
    assert ok is False
    assert "Request error" in err


@pytest.mark.asyncio
async def test_send_webhook_generic_exception(monkeypatch):
    class _BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("unexpected")

    monkeypatch.setattr(notifier.httpx, "AsyncClient", lambda timeout=30.0: _BrokenClient())
    ok, err = await notifier.send_webhook(_channel(), _scheduled_run(), _schedule())
    assert ok is False
    assert "Unexpected error" in err


@pytest.mark.asyncio
async def test_send_email_not_implemented():
    ch = _channel(channel_type="email")
    ok, err = await notifier.send_email(ch, _scheduled_run(), _schedule())
    assert ok is False
    assert "not yet implemented" in err


@pytest.mark.asyncio
async def test_send_notifications_unknown_channel_type():
    """send_notifications logs error for unknown channel type."""
    unknown_channel = _channel(channel_type="sms", channel_id=200)

    sent, errors = await notifier.send_notifications(
        _scheduled_run(),
        _schedule(),
        [unknown_channel],
    )
    assert len(sent) == 0
    assert 200 in errors
    assert "Unknown channel type" in errors[200]


@pytest.mark.asyncio
async def test_get_template_context_no_duration():
    """_get_template_context returns 'N/A' duration when timestamps are missing."""
    run = _scheduled_run()
    run.started_at = None
    run.completed_at = None
    ctx = notifier._get_template_context(run, _schedule())
    assert ctx["duration"] == "N/A"
