"""Integration tests for api/routes/schedules.py"""
import pytest
from unittest.mock import MagicMock, patch


# Stub out scheduler_service so tests never actually schedule jobs
@pytest.fixture(autouse=True)
def stub_scheduler(monkeypatch):
    fake = MagicMock()
    fake.is_running = False
    fake.get_all_jobs_status.return_value = []
    monkeypatch.setattr("api.routes.schedules.scheduler_service", fake)
    return fake


def _make_project(client, name="Schedule Project"):
    res = client.post(
        "/api/projects",
        json={"name": name, "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    )
    assert res.status_code == 200
    return res.json()["id"]


def _make_schedule(client, project_id, name="Nightly Run"):
    return client.post(
        f"/api/projects/{project_id}/schedules",
        json={
            "name": name,
            "cron_expression": "0 2 * * *",
            "timezone": "UTC",
            "target_type": "test_case_ids",
            "target_test_case_ids": [1],
            "enabled": True,
        },
    )


def test_list_schedules_empty(client):
    pid = _make_project(client, "Empty Sched Project")
    res = client.get(f"/api/projects/{pid}/schedules")
    assert res.status_code == 200
    assert res.json() == []


def test_list_schedules_unknown_project(client):
    res = client.get("/api/projects/9999999/schedules")
    assert res.status_code == 404


def test_create_schedule_success(client):
    pid = _make_project(client)
    res = _make_schedule(client, pid)
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Nightly Run"
    assert data["cron_expression"] == "0 2 * * *"


def test_create_schedule_unknown_project(client):
    res = client.post(
        "/api/projects/9999999/schedules",
        json={"name": "x", "cron_expression": "0 * * * *", "timezone": "UTC",
              "target_type": "test_case_ids", "target_test_case_ids": [1]},
    )
    assert res.status_code == 404


def test_create_schedule_invalid_cron(client):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={"name": "bad cron", "cron_expression": "not-a-cron", "timezone": "UTC",
              "target_type": "test_case_ids", "target_test_case_ids": [1]},
    )
    assert res.status_code == 422


def test_create_schedule_invalid_timezone(client):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={"name": "bad tz", "cron_expression": "0 * * * *", "timezone": "Not/AZone",
              "target_type": "test_case_ids", "target_test_case_ids": [1]},
    )
    assert res.status_code == 422


def test_create_schedule_missing_target_test_case_ids(client):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={"name": "missing ids", "cron_expression": "0 * * * *", "timezone": "UTC",
              "target_type": "test_case_ids"},
    )
    assert res.status_code == 400


def test_create_schedule_missing_target_tags(client):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={"name": "missing tags", "cron_expression": "0 * * * *", "timezone": "UTC",
              "target_type": "tags"},
    )
    assert res.status_code == 400


def test_get_schedule(client):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    res = client.get(f"/api/projects/{pid}/schedules/{sid}")
    assert res.status_code == 200
    assert res.json()["id"] == sid


def test_get_schedule_not_found(client):
    pid = _make_project(client)
    res = client.get(f"/api/projects/{pid}/schedules/9999999")
    assert res.status_code == 404


def test_update_schedule(client):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    res = client.put(
        f"/api/projects/{pid}/schedules/{sid}",
        json={"name": "Updated Schedule", "cron_expression": "0 3 * * *",
              "timezone": "UTC", "target_type": "test_case_ids",
              "target_test_case_ids": [1], "retry_max": 0, "enabled": False},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Schedule"


def test_update_schedule_not_found(client):
    pid = _make_project(client)
    res = client.put(
        f"/api/projects/{pid}/schedules/9999999",
        json={"name": "x"},
    )
    assert res.status_code == 404


def test_delete_schedule(client):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    res = client.delete(f"/api/projects/{pid}/schedules/{sid}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"


def test_delete_schedule_not_found(client):
    pid = _make_project(client)
    res = client.delete(f"/api/projects/{pid}/schedules/9999999")
    assert res.status_code == 404


def test_get_schedule_runs(client):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    res = client.get(f"/api/projects/{pid}/schedules/{sid}/runs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_get_schedule_runs_not_found(client):
    pid = _make_project(client)
    res = client.get(f"/api/projects/{pid}/schedules/9999999/runs")
    assert res.status_code == 404


def test_trigger_schedule_now(client, monkeypatch):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    async def _noop(schedule_id, skip_claim=False):
        return None

    monkeypatch.setattr("scheduler.executor.execute_scheduled_run", _noop)

    res = client.post(f"/api/projects/{pid}/schedules/{sid}/run")
    assert res.status_code == 200
    assert res.json()["status"] == "triggered"


def test_trigger_schedule_not_found(client):
    pid = _make_project(client)
    res = client.post(f"/api/projects/{pid}/schedules/9999999/run")
    assert res.status_code == 404


def test_get_project_scheduled_runs(client):
    pid = _make_project(client)
    res = client.get(f"/api/projects/{pid}/scheduled-runs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_get_project_scheduled_runs_unknown_project(client):
    res = client.get("/api/projects/9999999/scheduled-runs")
    assert res.status_code == 404


def test_validate_cron_expression_helper():
    from api.routes.schedules import validate_cron_expression, validate_timezone
    assert validate_cron_expression("0 * * * *") == "0 * * * *"
    assert validate_timezone("America/New_York") == "America/New_York"

    with pytest.raises(ValueError, match="Invalid cron"):
        validate_cron_expression("not-a-cron")

    with pytest.raises(ValueError, match="Unknown timezone"):
        validate_timezone("Fake/Zone")


def test_create_schedule_disabled_does_not_add_job(client, stub_scheduler):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={
            "name": "Disabled",
            "cron_expression": "0 2 * * *",
            "timezone": "UTC",
            "target_type": "test_case_ids",
            "target_test_case_ids": [1],
            "enabled": False,
        },
    )
    assert res.status_code == 200
    stub_scheduler.add_schedule.assert_not_called()


def test_create_schedule_notification_channel_not_found(client):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={
            "name": "With channel",
            "cron_expression": "0 2 * * *",
            "timezone": "UTC",
            "target_type": "test_case_ids",
            "target_test_case_ids": [1],
            "notification_channel_ids": [99999],
        },
    )
    assert res.status_code == 400
    assert "not found" in res.json()["detail"].lower()


def test_create_schedule_notification_channel_wrong_project(client):
    pid_a = _make_project(client, "A")
    pid_b = _make_project(client, "B")

    channel = client.post(
        f"/api/projects/{pid_b}/notifications",
        json={"name": "email", "channel_type": "email", "email_recipients": ["x@example.com"]},
    )
    assert channel.status_code == 200
    channel_id = channel.json()["id"]

    res = client.post(
        f"/api/projects/{pid_a}/schedules",
        json={
            "name": "Wrong channel",
            "cron_expression": "0 2 * * *",
            "timezone": "UTC",
            "target_type": "test_case_ids",
            "target_test_case_ids": [1],
            "notification_channel_ids": [channel_id],
        },
    )
    assert res.status_code == 400
    assert "does not belong" in res.json()["detail"]


def test_schedule_update_request_validators_allow_none():
    from api.routes.schedules import ScheduleUpdateRequest

    req = ScheduleUpdateRequest(name="x", cron_expression=None, timezone=None)
    assert req.cron_expression is None
    assert req.timezone is None


def test_update_schedule_when_cron_timezone_unchanged(client, stub_scheduler, monkeypatch):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    import api.routes.schedules as schedules_mod
    original_get_schedule = schedules_mod.crud.get_schedule
    monkeypatch.setattr(
        schedules_mod.crud,
        "update_schedule",
        lambda s, schedule_id, data: original_get_schedule(s, schedule_id),
    )

    res = client.put(
        f"/api/projects/{pid}/schedules/{sid}",
        json={"name": "Name only update"},
    )
    assert res.status_code == 200
    stub_scheduler.update_schedule.assert_called()


def test_update_schedule_returns_none_after_lookup(client, monkeypatch):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    import api.routes.schedules as schedules_mod
    monkeypatch.setattr(schedules_mod.crud, "update_schedule", lambda s, schedule_id, data: None)

    res = client.put(
        f"/api/projects/{pid}/schedules/{sid}",
        json={"name": "will fail"},
    )
    assert res.status_code == 404


def test_delete_schedule_when_crud_delete_returns_false(client, monkeypatch):
    pid = _make_project(client)
    sid = _make_schedule(client, pid).json()["id"]

    import api.routes.schedules as schedules_mod
    monkeypatch.setattr(schedules_mod.crud, "delete_schedule", lambda s, schedule_id: False)

    res = client.delete(f"/api/projects/{pid}/schedules/{sid}")
    assert res.status_code == 404


def test_project_scheduled_runs_uses_unknown_schedule_name(client, monkeypatch):
    from datetime import datetime
    from db.models import RunStatus

    pid = _make_project(client)

    import api.routes.schedules as schedules_mod

    fake_run = type("R", (), {
        "id": 1,
        "schedule_id": 777,
        "project_id": pid,
        "thread_id": "t-1",
        "status": RunStatus.RUNNING,
        "started_at": datetime.utcnow(),
        "completed_at": None,
        "test_count": 1,
        "pass_count": 0,
        "fail_count": 0,
        "notifications_sent": None,
        "notification_errors": None,
        "created_at": datetime.utcnow(),
    })

    monkeypatch.setattr(schedules_mod.crud, "get_scheduled_runs_by_project", lambda s, p, skip=0, limit=50: [fake_run])
    monkeypatch.setattr(schedules_mod.crud, "get_schedule", lambda s, sid: None)

    res = client.get(f"/api/projects/{pid}/scheduled-runs")
    assert res.status_code == 200
    assert res.json()[0]["schedule_name"] == "Unknown"


def test_create_schedule_with_multiple_valid_notification_channels(client):
    pid = _make_project(client, "With channels")

    ch1 = client.post(
        f"/api/projects/{pid}/notifications",
        json={"name": "email-1", "channel_type": "email", "email_recipients": ["a@example.com"]},
    )
    ch2 = client.post(
        f"/api/projects/{pid}/notifications",
        json={"name": "email-2", "channel_type": "email", "email_recipients": ["b@example.com"]},
    )
    assert ch1.status_code == 200
    assert ch2.status_code == 200

    res = client.post(
        f"/api/projects/{pid}/schedules",
        json={
            "name": "valid channels",
            "cron_expression": "0 2 * * *",
            "timezone": "UTC",
            "target_type": "test_case_ids",
            "target_test_case_ids": [1],
            "notification_channel_ids": [ch1.json()["id"], ch2.json()["id"]],
        },
    )
    assert res.status_code == 200


def test_debug_scheduler_status(client):
    res = client.get("/api/debug/scheduler/status")
    assert res.status_code == 200
    assert "is_running" in res.json()
