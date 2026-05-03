"""Integration tests for api/routes/notifications.py"""
import pytest
from unittest.mock import AsyncMock, patch


def _create_project(client, name="Notif Project"):
    res = client.post(
        "/api/projects",
        json={"name": name, "description": "", "base_url": "https://example.com",
              "config": "{}", "base_prompt": "", "page_load_state": "load"},
    )
    assert res.status_code == 200
    return res.json()["id"]


def _create_channel(client, project_id, channel_type="webhook", name="My Webhook"):
    return client.post(
        f"/api/projects/{project_id}/notifications",
        json={
            "name": name,
            "channel_type": channel_type,
            "enabled": True,
            "webhook_url": "https://hooks.example.com/notify",
            "notify_on": "failure",
        },
    )


def test_list_channels_empty(client):
    pid = _create_project(client)
    res = client.get(f"/api/projects/{pid}/notifications")
    assert res.status_code == 200
    assert res.json() == []


def test_list_channels_unknown_project(client):
    res = client.get("/api/projects/9999999/notifications")
    assert res.status_code == 404


def test_create_channel_webhook(client):
    pid = _create_project(client)
    res = _create_channel(client, pid)
    assert res.status_code == 200
    assert res.json()["channel_type"] == "webhook"


def test_create_channel_unknown_project(client):
    res = _create_channel(client, 9999999)
    assert res.status_code == 404


def test_create_channel_with_email_recipients(client):
    pid = _create_project(client)
    res = client.post(
        f"/api/projects/{pid}/notifications",
        json={
            "name": "Email Channel",
            "channel_type": "email",
            "enabled": True,
            "email_recipients": ["a@example.com", "b@example.com"],
            "notify_on": "always",
        },
    )
    assert res.status_code == 200
    assert res.json()["channel_type"] == "email"


def test_get_channel(client):
    pid = _create_project(client)
    cid = _create_channel(client, pid).json()["id"]

    res = client.get(f"/api/projects/{pid}/notifications/{cid}")
    assert res.status_code == 200
    assert res.json()["id"] == cid


def test_get_channel_not_found(client):
    pid = _create_project(client)
    res = client.get(f"/api/projects/{pid}/notifications/9999999")
    assert res.status_code == 404


def test_update_channel(client):
    pid = _create_project(client)
    cid = _create_channel(client, pid).json()["id"]

    res = client.put(
        f"/api/projects/{pid}/notifications/{cid}",
        json={"name": "Updated Webhook", "channel_type": "webhook", "enabled": False, "notify_on": "always"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Webhook"


def test_update_channel_not_found(client):
    pid = _create_project(client)
    res = client.put(
        f"/api/projects/{pid}/notifications/9999999",
        json={"name": "x"},
    )
    assert res.status_code == 404


def test_delete_channel(client):
    pid = _create_project(client)
    cid = _create_channel(client, pid).json()["id"]

    res = client.delete(f"/api/projects/{pid}/notifications/{cid}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"


def test_delete_channel_not_found(client):
    pid = _create_project(client)
    res = client.delete(f"/api/projects/{pid}/notifications/9999999")
    assert res.status_code == 404


def test_test_notification_channel_webhook_success(client, monkeypatch):
    pid = _create_project(client)
    cid = _create_channel(client, pid, channel_type="webhook").json()["id"]

    async def _mock_send_webhook(channel, run, schedule):
        return True, ""

    monkeypatch.setattr("scheduler.notifier.send_webhook", _mock_send_webhook)

    res = client.post(f"/api/projects/{pid}/notifications/{cid}/test", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_test_notification_channel_webhook_failure(client, monkeypatch):
    pid = _create_project(client)
    cid = _create_channel(client, pid, channel_type="webhook").json()["id"]

    async def _mock_fail(channel, run, schedule):
        return False, "connection refused"

    monkeypatch.setattr("scheduler.notifier.send_webhook", _mock_fail)

    res = client.post(f"/api/projects/{pid}/notifications/{cid}/test", json={})
    assert res.status_code == 400
    assert "connection refused" in res.json()["detail"]


def test_test_notification_channel_unknown_type(client):
    """Channel types that are not webhook/email return 400."""
    pid = _create_project(client)
    # Create a webhook channel then test it with an injected bad channel type by mutating db
    cid = _create_channel(client, pid, channel_type="webhook", name="Unknown Type").json()["id"]

    # Patch channel_type via the get_notification_channel mock to return an unsupported type
    from api.routes import notifications as notif_mod
    from unittest.mock import patch

    class _FakeChannel:
        id = cid
        project_id = pid
        channel_type = "sms"  # unsupported

    with patch.object(notif_mod.crud, "get_notification_channel", return_value=_FakeChannel()):
        res = client.post(f"/api/projects/{pid}/notifications/{cid}/test", json={})
    assert res.status_code == 400


def test_test_notification_channel_not_found(client):
    pid = _create_project(client)
    res = client.post(f"/api/projects/{pid}/notifications/9999999/test", json={})
    assert res.status_code == 404
