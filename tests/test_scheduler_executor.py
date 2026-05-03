import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import scheduler.executor as scheduler_executor
from db.models import RunStatus


def _schedule(**overrides):
    base = {
        "id": 1,
        "project_id": 10,
        "enabled": True,
        "target_type": "test_case_ids",
        "retry_max": 0,
        "retry_mode": "simple",
        "browser": None,
        "timezone": "UTC",
        "cron_expression": "*/5 * * * *",
        "get_target_test_case_ids": lambda: [101],
        "get_target_tags": lambda: [],
        "get_notification_channel_ids": lambda: [501, 502, 503],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _test_case():
    return SimpleNamespace(
        id=101,
        name="Login flow",
        steps=json.dumps([{"action": "navigate", "value": "/login"}]),
        get_fixture_ids=lambda: [],
    )


def _project():
    return SimpleNamespace(id=10, base_url="https://example.com")


@pytest.mark.asyncio
async def test_execute_scheduled_run_skips_when_claim_fails(monkeypatch):
    session = MagicMock()

    @contextmanager
    def fake_get_session():
        yield session

    get_schedule = MagicMock()
    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "try_claim_schedule_execution", lambda s, sid: False)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", get_schedule)

    await scheduler_executor.execute_scheduled_run(1)

    get_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_execute_scheduled_run_no_test_cases_updates_times(monkeypatch):
    session = MagicMock()
    sched = _schedule(get_target_test_case_ids=lambda: [])

    @contextmanager
    def fake_get_session():
        yield session

    update_times = MagicMock()
    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", update_times)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    update_times.assert_called_once()


@pytest.mark.asyncio
async def test_execute_scheduled_run_single_test_case_pass(monkeypatch):
    session = MagicMock()
    sched = _schedule(retry_max=0, retry_mode="simple")
    tc = _test_case()

    @contextmanager
    def fake_get_session():
        yield session

    async def stream_events(*args, **kwargs):
        yield {
            "type": "step_completed",
            "step_number": 1,
            "status": "passed",
            "duration": 25,
            "error": None,
            "screenshot": None,
        }

    fake_client = SimpleNamespace(execute_stream=stream_events)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, schedule_id=1, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: tc)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77))
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", MagicMock())
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)

    update_test_run = MagicMock()
    create_step = MagicMock()
    update_scheduled_run = MagicMock()
    notify = AsyncMock()

    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", notify)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    create_step.assert_called_once()
    assert any(
        len(call.args) >= 3 and call.args[2].get("status") == RunStatus.PASSED
        for call in update_scheduled_run.call_args_list
    )
    notify.assert_awaited_once_with(session, 55)


@pytest.mark.asyncio
async def test_send_scheduled_run_notifications_filters_notify_on(monkeypatch):
    session = MagicMock()
    run = SimpleNamespace(id=301, schedule_id=1, status=RunStatus.PASSED)
    schedule = _schedule(get_notification_channel_ids=lambda: [1, 2, 3])
    channels = [
        SimpleNamespace(id=1, enabled=True, notify_on="always"),
        SimpleNamespace(id=2, enabled=True, notify_on="success"),
        SimpleNamespace(id=3, enabled=True, notify_on="failure"),
    ]

    monkeypatch.setattr(scheduler_executor.crud, "get_scheduled_run", lambda s, rid: run)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_notification_channels_by_ids", lambda s, ids: channels)

    async def fake_send_notifications(scheduled_run, schedule_obj, channels_to_notify):
        assert len(channels_to_notify) == 2
        return [1, 2], {3: "skipped"}

    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr("scheduler.notifier.send_notifications", fake_send_notifications)

    await scheduler_executor.send_scheduled_run_notifications(session, 301)

    update_scheduled_run.assert_called_once()


@pytest.mark.asyncio
async def test_execute_scheduled_run_project_not_found(monkeypatch):
    session = MagicMock()
    sched = _schedule()

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: None)
    log_error = MagicMock()
    monkeypatch.setattr(scheduler_executor.logger, "error", log_error)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    log_error.assert_called()


@pytest.mark.asyncio
async def test_execute_scheduled_run_schedule_disabled(monkeypatch):
    session = MagicMock()
    sched = _schedule(enabled=False)

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    log_info = MagicMock()
    monkeypatch.setattr(scheduler_executor.logger, "info", log_info)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert any("disabled" in str(call) for call in log_info.call_args_list)


@pytest.mark.asyncio
async def test_execute_scheduled_run_with_fixture_prepending(monkeypatch):
    session = MagicMock()
    sched = _schedule(retry_max=0)
    tc = _test_case()
    tc.get_fixture_ids = lambda: [77]

    fixture = SimpleNamespace(
        id=77,
        name="Login Setup",
        get_setup_steps=lambda: [{"action": "navigate", "value": "/login"}],
    )

    @contextmanager
    def fake_get_session():
        yield session

    async def stream_events(*args, **kwargs):
        yield {
            "type": "step_completed",
            "step_number": 1,
            "status": "passed",
            "duration": 25,
        }
        yield {
            "type": "step_completed",
            "step_number": 2,
            "status": "passed",
            "duration": 50,
        }

    fake_client = SimpleNamespace(execute_stream=stream_events)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: tc)
    monkeypatch.setattr(scheduler_executor.crud, "get_fixtures_by_ids", lambda s, ids: [fixture])
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)

    create_step = MagicMock()
    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    log_info = MagicMock()
    monkeypatch.setattr(scheduler_executor.logger, "info", log_info)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert any("fixture" in str(call).lower() for call in log_info.call_args_list)


@pytest.mark.asyncio
async def test_execute_scheduled_run_with_simple_retry_mode(monkeypatch):
    session = MagicMock()
    sched = _schedule(retry_max=1, retry_mode="simple")
    tc = _test_case()

    @contextmanager
    def fake_get_session():
        yield session

    attempt_count = [0]

    async def stream_events(*args, **kwargs):
        attempt_count[0] += 1
        if attempt_count[0] == 1:
            yield {"type": "step_completed", "step_number": 1, "status": "failed", "error": "Transient"}
        else:
            yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 25}

    fake_client = SimpleNamespace(execute_stream=stream_events)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: tc)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)

    create_step = MagicMock()
    update_test_run = MagicMock()
    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert attempt_count[0] > 1


@pytest.mark.asyncio
async def test_execute_scheduled_run_executor_error_handling(monkeypatch):
    session = MagicMock()
    sched = _schedule(retry_max=0)
    tc = _test_case()

    @contextmanager
    def fake_get_session():
        yield session

    async def stream_events(*args, **kwargs):
        yield {"type": "error", "error": "Connection refused"}

    fake_client = SimpleNamespace(execute_stream=stream_events)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: tc)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)

    create_step = MagicMock()
    update_test_run = MagicMock()
    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    log_error = MagicMock()
    monkeypatch.setattr(scheduler_executor.logger, "error", log_error)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    log_error.assert_called()


@pytest.mark.asyncio
async def test_execute_scheduled_run_with_target_tags(monkeypatch):
    session = MagicMock()
    sched = _schedule(target_type="tags", get_target_test_case_ids=lambda: [])
    sched.get_target_tags = lambda: ["smoke", "critical"]
    tc1 = _test_case()
    tc2 = _test_case()
    tc2.id = 102

    @contextmanager
    def fake_get_session():
        yield session

    async def stream_events(*args, **kwargs):
        yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 25}

    fake_client = SimpleNamespace(execute_stream=stream_events)

    def get_tc(s, tc_id):
        return tc1 if tc_id == 101 else tc2

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "get_test_cases_by_tags", lambda s, pid, tags: [tc1, tc2])
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", get_tc)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77 + (data.test_case_id - 101)))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)

    create_step = MagicMock()
    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert create_step.call_count >= 1


@pytest.mark.asyncio
async def test_execute_scheduled_run_with_browser_override(monkeypatch):
    session = MagicMock()
    sched = _schedule(browser="firefox", retry_max=0)
    tc = _test_case()

    @contextmanager
    def fake_get_session():
        yield session

    received_options = [None]

    async def stream_events(base_url, steps, test_id, options):
        received_options[0] = options
        yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 25}

    fake_client = SimpleNamespace(execute_stream=stream_events)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: tc)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)

    create_step = MagicMock()
    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", create_step)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert received_options[0] is not None
    assert received_options[0].get("browser") == "firefox"


@pytest.mark.asyncio
async def test_send_scheduled_run_notifications_with_failure_status(monkeypatch):
    session = MagicMock()
    run = SimpleNamespace(id=301, schedule_id=1, status=RunStatus.FAILED)
    schedule = _schedule(get_notification_channel_ids=lambda: [1, 2])
    channels = [
        SimpleNamespace(id=1, enabled=True, notify_on="always"),
        SimpleNamespace(id=2, enabled=True, notify_on="failure"),
    ]

    monkeypatch.setattr(scheduler_executor.crud, "get_scheduled_run", lambda s, rid: run)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_notification_channels_by_ids", lambda s, ids: channels)

    async def fake_send_notifications(scheduled_run, schedule_obj, channels_to_notify):
        return [1, 2], {}

    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)
    monkeypatch.setattr("scheduler.notifier.send_notifications", fake_send_notifications)

    await scheduler_executor.send_scheduled_run_notifications(session, 301)

    update_scheduled_run.assert_called_once()
    payload = update_scheduled_run.call_args[0][2]
    assert payload["notifications_sent"] == json.dumps([1, 2])


@pytest.mark.asyncio
async def test_execute_scheduled_run_schedule_not_found_after_claim(monkeypatch):
    session = MagicMock()

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "try_claim_schedule_execution", lambda s, sid: True)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: None)
    log_error = MagicMock()
    monkeypatch.setattr(scheduler_executor.logger, "error", log_error)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=False)

    log_error.assert_called()


@pytest.mark.asyncio
async def test_execute_scheduled_run_tags_target_without_tags_updates_times(monkeypatch):
    session = MagicMock()
    sched = _schedule(target_type="tags", get_target_test_case_ids=lambda: [], get_target_tags=lambda: [])

    @contextmanager
    def fake_get_session():
        yield session

    update_times = MagicMock()
    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", update_times)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    update_times.assert_called_once()


@pytest.mark.asyncio
async def test_execute_scheduled_run_invalid_json_steps_are_skipped(monkeypatch):
    session = MagicMock()
    sched = _schedule(retry_max=0)
    tc = _test_case()
    tc.steps = "{invalid-json"

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, data: SimpleNamespace(id=55, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: tc)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, data: SimpleNamespace(id=77))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: SimpleNamespace(execute_stream=AsyncMock()))
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", MagicMock())
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)


@pytest.mark.asyncio
async def test_send_notifications_guard_paths(monkeypatch):
    session = MagicMock()

    # Missing scheduled run
    monkeypatch.setattr(scheduler_executor.crud, "get_scheduled_run", lambda s, rid: None)
    await scheduler_executor.send_scheduled_run_notifications(session, 1)

    # Missing schedule
    run = SimpleNamespace(id=2, schedule_id=2, status=RunStatus.PASSED)
    monkeypatch.setattr(scheduler_executor.crud, "get_scheduled_run", lambda s, rid: run)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: None)
    await scheduler_executor.send_scheduled_run_notifications(session, 2)

    # No channel ids
    sched_no_channels = _schedule(get_notification_channel_ids=lambda: [])
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched_no_channels)
    await scheduler_executor.send_scheduled_run_notifications(session, 2)

    # Channel IDs configured but no channels found
    sched_ids = _schedule(get_notification_channel_ids=lambda: [1])
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched_ids)
    monkeypatch.setattr(scheduler_executor.crud, "get_notification_channels_by_ids", lambda s, ids: [])
    await scheduler_executor.send_scheduled_run_notifications(session, 2)


@pytest.mark.asyncio
async def test_send_notifications_no_matching_channels_and_empty_results(monkeypatch):
    session = MagicMock()
    run = SimpleNamespace(id=301, schedule_id=1, status=RunStatus.PASSED)
    schedule = _schedule(get_notification_channel_ids=lambda: [1, 2])
    channels = [
        SimpleNamespace(id=1, enabled=False, notify_on="always"),
        SimpleNamespace(id=2, enabled=True, notify_on="failure"),
    ]

    monkeypatch.setattr(scheduler_executor.crud, "get_scheduled_run", lambda s, rid: run)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_notification_channels_by_ids", lambda s, ids: channels)

    update_scheduled_run = MagicMock()
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", update_scheduled_run)

    # No matching channels => returns before send_notifications
    await scheduler_executor.send_scheduled_run_notifications(session, 301)
    update_scheduled_run.assert_not_called()

    # Now provide a matching channel but notifier returns no sent/errors => still no update
    channels2 = [SimpleNamespace(id=3, enabled=True, notify_on="always")]
    monkeypatch.setattr(scheduler_executor.crud, "get_notification_channels_by_ids", lambda s, ids: channels2)

    async def fake_send_notifications(_run, _schedule, _channels):
        return [], {}

    monkeypatch.setattr("scheduler.notifier.send_notifications", fake_send_notifications)
    await scheduler_executor.send_scheduled_run_notifications(session, 301)
    update_scheduled_run.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_test_case_not_found_skips(monkeypatch):
    session = MagicMock()
    schedule = _schedule(retry_max=0)

    @contextmanager
    def fake_get_session():
        yield session

    async def fake_stream(*args, **kwargs):
        return
        yield

    fake_client = SimpleNamespace(execute_stream=fake_stream)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(
        scheduler_executor.crud,
        "create_scheduled_run",
        lambda s, d: SimpleNamespace(id=1, status=RunStatus.RUNNING),
    )
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: None)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, d: SimpleNamespace(id=1))
    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", MagicMock())
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)


@pytest.mark.asyncio
async def test_scheduler_tags_no_matching_test_cases(monkeypatch):
    session = MagicMock()
    schedule = _schedule(target_type="tags", get_target_tags=lambda: ["smoke"])

    @contextmanager
    def fake_get_session():
        yield session

    update_times = MagicMock()
    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "get_test_cases_by_tags", lambda s, pid, tags: [])
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", update_times)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    update_times.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_exception_in_test_execution(monkeypatch):
    session = MagicMock()
    schedule = _schedule(retry_max=0)
    test_case = _test_case()

    @contextmanager
    def fake_get_session():
        yield session

    async def boom(*args, **kwargs):
        raise RuntimeError("Executor exploded")
        yield

    fake_client = SimpleNamespace(execute_stream=boom)
    update_test_run = MagicMock()

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(
        scheduler_executor.crud,
        "create_scheduled_run",
        lambda s, d: SimpleNamespace(id=1, status=RunStatus.RUNNING),
    )
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: test_case)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, d: SimpleNamespace(id=1))
    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", update_test_run)
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", MagicMock())
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert update_test_run.called


@pytest.mark.asyncio
async def test_scheduler_intelligent_retry_classify_exception_defaults_to_retry(monkeypatch):
    session = MagicMock()
    schedule = _schedule(retry_max=1, retry_mode="intelligent")
    test_case = _test_case()

    @contextmanager
    def fake_get_session():
        yield session

    attempt = [0]

    async def fake_stream(*args, **kwargs):
        attempt[0] += 1
        if attempt[0] == 1:
            yield {"type": "step_completed", "step_number": 1, "status": "failed", "error": "err", "duration": 10}
        else:
            yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 10}

    fake_client = SimpleNamespace(execute_stream=fake_stream)

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(
        scheduler_executor.crud,
        "create_scheduled_run",
        lambda s, d: SimpleNamespace(id=1, status=RunStatus.RUNNING),
    )
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: test_case)
    monkeypatch.setattr(
        scheduler_executor.crud,
        "create_test_run",
        lambda s, d: SimpleNamespace(id=attempt[0] + 10),
    )
    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", MagicMock())
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: fake_client)
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())

    monkeypatch.setattr(scheduler_executor, "classify_failure", AsyncMock(side_effect=RuntimeError("boom")))

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    assert attempt[0] == 2


def _make_executor_monkeypatch(monkeypatch, session, schedule, test_case, stream_fn, **extra_crud):
    """Helper to reduce boilerplate for executor tests."""
    from contextlib import contextmanager

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: schedule)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "create_scheduled_run", lambda s, d: SimpleNamespace(id=1, status=RunStatus.RUNNING))
    monkeypatch.setattr(scheduler_executor.crud, "get_test_case", lambda s, tc_id: test_case)
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run", lambda s, d: SimpleNamespace(id=1))
    monkeypatch.setattr(scheduler_executor.crud, "update_test_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "create_test_run_step", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_scheduled_run", MagicMock())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", MagicMock())
    monkeypatch.setattr(scheduler_executor, "PlaywrightExecutorClient", lambda: SimpleNamespace(execute_stream=stream_fn))
    monkeypatch.setattr(scheduler_executor, "resolve_references", lambda s, pid, steps: steps)
    monkeypatch.setattr(scheduler_executor, "mask_passwords_in_steps", lambda steps: steps)
    monkeypatch.setattr(scheduler_executor, "send_scheduled_run_notifications", AsyncMock())
    for attr, val in extra_crud.items():
        monkeypatch.setattr(scheduler_executor.crud, attr, val)


@pytest.mark.asyncio
async def test_execute_unknown_target_type_yields_no_test_cases(monkeypatch):
    """Branch 59->65: target_type is neither test_case_ids nor tags → empty test_case_ids."""
    session = MagicMock()
    sched = _schedule(target_type="unknown_type", get_target_test_case_ids=lambda: [])
    update_times = MagicMock()

    from contextlib import contextmanager

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_executor, "get_session", fake_get_session)
    monkeypatch.setattr(scheduler_executor.crud, "get_schedule", lambda s, sid: sched)
    monkeypatch.setattr(scheduler_executor.crud, "get_project", lambda s, pid: _project())
    monkeypatch.setattr(scheduler_executor.crud, "update_schedule_run_times", update_times)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)

    update_times.assert_called_once()


@pytest.mark.asyncio
async def test_execute_fixture_with_no_steps_branch(monkeypatch):
    """Branches 124->122 and 129->133: fixture exists but has no setup_steps."""
    session = MagicMock()
    sched = _schedule(retry_max=0)
    tc = _test_case()
    tc.get_fixture_ids = lambda: [99]
    fixture_no_steps = SimpleNamespace(id=99, name="Empty Setup", get_setup_steps=lambda: [])

    async def stream_fn(*args, **kwargs):
        yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 10}

    _make_executor_monkeypatch(
        monkeypatch, session, sched, tc, stream_fn,
        get_fixtures_by_ids=lambda s, ids: [fixture_no_steps],
    )

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)


@pytest.mark.asyncio
async def test_execute_while_loop_exits_via_condition(monkeypatch):
    """Branch 149->287: while loop exits when max_retries is negative (loop never entered)."""
    session = MagicMock()
    # retry_max=-1 → max_retries=-1 → while 0 <= -1 is False immediately
    sched = _schedule(retry_max=-1, retry_mode="simple")
    tc = _test_case()

    async def stream_fn(*args, **kwargs):
        yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 10}

    _make_executor_monkeypatch(monkeypatch, session, sched, tc, stream_fn)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)


@pytest.mark.asyncio
async def test_execute_unknown_event_type_ignored(monkeypatch):
    """Branch 224->183: unknown event type in stream is silently ignored."""
    session = MagicMock()
    sched = _schedule(retry_max=0)
    tc = _test_case()

    async def stream_fn(*args, **kwargs):
        yield {"type": "test_started"}  # unknown type
        yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 10}

    _make_executor_monkeypatch(monkeypatch, session, sched, tc, stream_fn)

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)


@pytest.mark.asyncio
async def test_execute_intelligent_retry_with_model_dump_classification(monkeypatch):
    """Lines 262-270: intelligent retry with model_dump() classification result."""
    session = MagicMock()
    sched = _schedule(retry_max=1, retry_mode="intelligent")
    tc = _test_case()

    attempt = [0]

    async def stream_fn(*args, **kwargs):
        attempt[0] += 1
        if attempt[0] == 1:
            yield {"type": "step_completed", "step_number": 1, "status": "failed", "error": "timeout", "duration": 10}
        else:
            yield {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 10}

    _make_executor_monkeypatch(monkeypatch, session, sched, tc, stream_fn)

    class ClassificationResult:
        def model_dump(self):
            return {"retryable": True, "reason": "Transient timeout"}

    monkeypatch.setattr(scheduler_executor, "classify_failure", AsyncMock(return_value=ClassificationResult()))

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)
    assert attempt[0] == 2


@pytest.mark.asyncio
async def test_execute_intelligent_retry_not_retryable(monkeypatch):
    """Lines 280-282: intelligent retry classification says not retryable."""
    session = MagicMock()
    sched = _schedule(retry_max=2, retry_mode="intelligent")
    tc = _test_case()

    attempt = [0]

    async def stream_fn(*args, **kwargs):
        attempt[0] += 1
        yield {"type": "step_completed", "step_number": 1, "status": "failed", "error": "fatal", "duration": 10}

    _make_executor_monkeypatch(monkeypatch, session, sched, tc, stream_fn)

    monkeypatch.setattr(
        scheduler_executor,
        "classify_failure",
        AsyncMock(return_value={"retryable": False, "reason": "Element missing — not transient"}),
    )

    await scheduler_executor.execute_scheduled_run(1, skip_claim=True)
    # Should only attempt once (not retried)
    assert attempt[0] == 1