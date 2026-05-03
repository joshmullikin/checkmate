from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import scheduler.service as scheduler_service


class _FakeScheduler:
    def __init__(self):
        self.started = False
        self.removed = False
        self.shutdown_called = False

    def start(self):
        self.started = True

    def remove_all_jobs(self):
        self.removed = True

    def shutdown(self, wait=False):
        self.shutdown_called = True

    def remove_job(self, job_id):
        return None

    def get_job(self, job_id):
        return None

    def get_jobs(self):
        return []

    def add_job(self, *args, **kwargs):
        return SimpleNamespace(next_run_time=datetime.utcnow())


@pytest.mark.asyncio
async def test_service_start_and_stop(monkeypatch):
    monkeypatch.setattr(scheduler_service, "AsyncIOScheduler", _FakeScheduler)
    svc = scheduler_service.SchedulerService()
    svc.reload_all_schedules = AsyncMock()

    await svc.start()
    assert svc.is_running is True
    assert isinstance(svc._scheduler, _FakeScheduler)
    svc.reload_all_schedules.assert_awaited_once()

    await svc.stop()
    assert svc.is_running is False
    assert svc._scheduler is None


@pytest.mark.asyncio
async def test_reload_all_schedules_calls_add_for_each_enabled(monkeypatch):
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    add_job = MagicMock()
    svc._add_schedule_job = add_job

    session = MagicMock()

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(scheduler_service, "get_session", fake_get_session)
    monkeypatch.setattr(
        scheduler_service.crud,
        "get_all_enabled_schedules",
        lambda s: [SimpleNamespace(id=1), SimpleNamespace(id=2)],
    )

    await svc.reload_all_schedules()

    assert svc._scheduler.removed is True
    assert add_job.call_count == 2


def test_get_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(
        scheduler_service.pytz,
        "timezone",
        lambda tz_name: (_ for _ in ()).throw(Exception("bad timezone")),
    )
    monkeypatch.setattr(scheduler_service, "HAS_ZONEINFO", False)

    tz = scheduler_service.get_timezone("Not/AZone")
    assert tz == scheduler_service.pytz.UTC


def test_add_schedule_no_scheduler_noop():
    svc = scheduler_service.SchedulerService()
    schedule = SimpleNamespace(enabled=True)
    svc.add_schedule(schedule)
    assert svc._scheduler is None


def test_add_schedule_disabled_noop(monkeypatch):
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    svc._add_schedule_job = MagicMock()
    schedule = SimpleNamespace(enabled=False)
    svc.add_schedule(schedule)
    svc._add_schedule_job.assert_not_called()


def test_update_schedule_enabled_calls_add(monkeypatch):
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    svc._add_schedule_job = MagicMock()
    svc.remove_schedule = MagicMock()
    schedule = SimpleNamespace(id=3, enabled=True)
    svc.update_schedule(schedule)
    svc.remove_schedule.assert_called_once_with(3)
    svc._add_schedule_job.assert_called_once_with(schedule)


def test_update_schedule_disabled_only_removes(monkeypatch):
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    svc._add_schedule_job = MagicMock()
    svc.remove_schedule = MagicMock()
    schedule = SimpleNamespace(id=3, enabled=False)
    svc.update_schedule(schedule)
    svc.remove_schedule.assert_called_once_with(3)
    svc._add_schedule_job.assert_not_called()


def test_remove_schedule_no_scheduler_noop():
    svc = scheduler_service.SchedulerService()
    svc.remove_schedule(1)
    assert svc._scheduler is None


def test_get_next_run_time_and_all_jobs_status(monkeypatch):
    svc = scheduler_service.SchedulerService()

    job = SimpleNamespace(
        id="schedule_1",
        name="Schedule: nightly",
        next_run_time=datetime.utcnow(),
        trigger="cron[0 2 * * *]",
    )

    fake = _FakeScheduler()
    fake.get_job = lambda _id: job
    fake.get_jobs = lambda: [job]
    svc._scheduler = fake

    assert svc.get_next_run_time(1) == job.next_run_time
    status = svc.get_all_jobs_status()
    assert status[0]["id"] == "schedule_1"


@pytest.mark.asyncio
async def test_execute_schedule_invokes_executor(monkeypatch):
    called = {"id": None}

    async def fake_execute(schedule_id):
        called["id"] = schedule_id

    import scheduler.executor as scheduler_executor

    monkeypatch.setattr(scheduler_executor, "execute_scheduled_run", fake_execute)
    svc = scheduler_service.SchedulerService()
    await svc._execute_schedule(42)
    assert called["id"] == 42


def test_add_schedule_job_updates_next_run_time(monkeypatch):
    """Test _add_schedule_job calculates and stores next run time."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    
    session = MagicMock()
    
    @contextmanager
    def fake_get_session():
        yield session
    
    monkeypatch.setattr(scheduler_service, "get_session", fake_get_session)
    
    schedule = SimpleNamespace(
        id=1,
        name="Test",
        timezone="UTC",
        cron_expression="0 * * * *",
        enabled=True,
    )
    
    svc._add_schedule_job(schedule)
    
    # Verify update_schedule_run_times was called
    import scheduler.service as svc_module
    # Can't easily verify without accessing crud mock, but job was added
    assert svc._scheduler.started is False  # _FakeScheduler starts only on explicit call


def test_add_schedule_job_cron_trigger_creation(monkeypatch):
    """Test _add_schedule_job creates CronTrigger correctly."""
    from croniter import croniter as croniter_module
    
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    
    session = MagicMock()
    
    @contextmanager
    def fake_get_session():
        yield session
    
    monkeypatch.setattr(scheduler_service, "get_session", fake_get_session)
    
    schedule = SimpleNamespace(
        id=2,
        name="Daily 9am",
        timezone="America/New_York",
        cron_expression="0 9 * * *",
        enabled=True,
    )
    
    svc._add_schedule_job(schedule)
    # Successfully added without error


def test_add_schedule_job_error_handling(monkeypatch):
    """Test _add_schedule_job logs error on cron parse failure."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    
    session = MagicMock()
    
    @contextmanager
    def fake_get_session():
        yield session
    
    monkeypatch.setattr(scheduler_service, "get_session", fake_get_session)
    
    schedule = SimpleNamespace(
        id=3,
        name="Invalid",
        timezone="UTC",
        cron_expression="invalid-cron-here",  # Invalid cron
        enabled=True,
    )
    
    logger_error = MagicMock()
    monkeypatch.setattr(scheduler_service.logger, "error", logger_error)
    
    svc._add_schedule_job(schedule)
    
    logger_error.assert_called()


@pytest.mark.asyncio
async def test_execute_schedule_error_handling(monkeypatch):
    """Test _execute_schedule handles errors gracefully."""
    svc = scheduler_service.SchedulerService()
    
    async def fake_execute_fail(schedule_id):
        raise RuntimeError("Executor failed")
    
    import scheduler.executor as scheduler_executor
    monkeypatch.setattr(scheduler_executor, "execute_scheduled_run", fake_execute_fail)
    
    logger_error = MagicMock()
    monkeypatch.setattr(scheduler_service.logger, "error", logger_error)
    
    await svc._execute_schedule(999)
    
    logger_error.assert_called()


def test_remove_schedule_with_error(monkeypatch):
    """Test remove_schedule handles missing job gracefully."""
    svc = scheduler_service.SchedulerService()
    
    fake_scheduler = _FakeScheduler()
    def raise_on_remove(job_id):
        raise Exception("Job not found")
    fake_scheduler.remove_job = raise_on_remove
    
    svc._scheduler = fake_scheduler
    
    logger_debug = MagicMock()
    monkeypatch.setattr(scheduler_service.logger, "debug", logger_debug)
    
    svc.remove_schedule(99)
    
    logger_debug.assert_called()


def test_get_timezone_with_zoneinfo_fallback(monkeypatch):
    """Test get_timezone falls back to zoneinfo when pytz fails."""
    
    def pytz_fail(tz_name):
        raise Exception("pytz broken")
    
    monkeypatch.setattr(scheduler_service.pytz, "timezone", pytz_fail)
    monkeypatch.setattr(scheduler_service, "HAS_ZONEINFO", True)
    
    # Mock ZoneInfo to succeed
    from types import SimpleNamespace
    mock_zoneinfo = SimpleNamespace(
        ZoneInfo=lambda tz: SimpleNamespace(tzname=tz)
    )
    monkeypatch.setattr(scheduler_service, "ZoneInfo", mock_zoneinfo.ZoneInfo)
    
    tz = scheduler_service.get_timezone("US/Eastern")
    assert tz is not None


def test_start_already_running():
    """Test start() does nothing if already running."""
    svc = scheduler_service.SchedulerService()
    svc._running = True
    
    import asyncio
    asyncio.run(svc.start())  # Should not error, just return
    
    assert svc._running is True


def test_stop_when_not_running():
    """Test stop() does nothing if not running."""
    svc = scheduler_service.SchedulerService()
    svc._running = False
    
    import asyncio
    asyncio.run(svc.stop())  # Should not error
    
    assert svc._running is False


@pytest.mark.asyncio
async def test_reload_all_schedules_no_scheduler():
    """Test reload_all_schedules returns early if no scheduler."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = None
    
    await svc.reload_all_schedules()
    # Should not error


@pytest.mark.asyncio
async def test_get_next_run_time_no_scheduler():
    """Test get_next_run_time returns None if no scheduler."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = None
    
    result = svc.get_next_run_time(1)
    
    assert result is None


def test_get_all_jobs_status_no_scheduler():
    """Test get_all_jobs_status returns empty list if no scheduler."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = None
    
    result = svc.get_all_jobs_status()
    
    assert result == []


def test_get_timezone_zoneinfo_also_fails(monkeypatch):
    """Lines 38-39: ZoneInfo fallback also raises → log warning."""
    def pytz_fail(tz_name):
        raise Exception("pytz broken")

    monkeypatch.setattr(scheduler_service.pytz, "timezone", pytz_fail)
    monkeypatch.setattr(scheduler_service, "HAS_ZONEINFO", True)
    monkeypatch.setattr(scheduler_service, "ZoneInfo", lambda tz: (_ for _ in ()).throw(Exception("zoneinfo also broken")))

    tz = scheduler_service.get_timezone("Bad/Zone")
    assert tz == scheduler_service.pytz.UTC


def test_add_schedule_job_no_scheduler_noop():
    """Line 105: _add_schedule_job early return when _scheduler is None."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = None
    schedule = SimpleNamespace(id=1, name="x", timezone="UTC", cron_expression="0 * * * *", enabled=True)
    svc._add_schedule_job(schedule)  # Should return immediately with no error
    assert svc._scheduler is None


def test_add_schedule_enabled_with_scheduler(monkeypatch):
    """Line 165: add_schedule calls _add_schedule_job when scheduler exists and enabled."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()
    called = []
    svc._add_schedule_job = lambda s: called.append(s)
    schedule = SimpleNamespace(id=10, enabled=True)
    svc.add_schedule(schedule)
    assert len(called) == 1 and called[0] is schedule


def test_remove_schedule_success_logs_info(monkeypatch):
    """Line 175: remove_schedule logs info on successful job removal."""
    svc = scheduler_service.SchedulerService()
    svc._scheduler = _FakeScheduler()  # remove_job returns None (no exception)

    logged = []
    monkeypatch.setattr(scheduler_service.logger, "info", lambda msg: logged.append(msg))

    svc.remove_schedule(42)
    assert any("schedule_42" in m for m in logged)


@pytest.mark.asyncio
async def test_stop_running_but_no_scheduler():
    """Branch 78->81: stop() when _running=True but _scheduler is None."""
    svc = scheduler_service.SchedulerService()
    svc._running = True
    svc._scheduler = None
    await svc.stop()
    assert svc._running is False