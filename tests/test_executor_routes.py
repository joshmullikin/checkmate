"""Tests for api/routes/executor.py"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def client_for_executor(client):
    """Reuse the conftest `client` fixture."""
    return client


# ---------------------------------------------------------------------------
# GET /api/executor/capabilities
# ---------------------------------------------------------------------------

def test_get_capabilities_request_error(client):
    """When executor is unreachable, returns recording_available=False."""
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.get = AsyncMock(side_effect=httpx.RequestError("down"))
        mock_cls.return_value = inst

        res = client.get("/api/executor/capabilities")

    assert res.status_code == 200
    assert res.json()["recording_available"] is False
    assert res.json()["headed_browsers"] == []


def test_get_capabilities_success_with_headed_browser(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "browsers": [
                {"id": "chrome", "headless": False},
                {"id": "chromium-headless", "headless": True},
            ]
        }
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = inst

        res = client.get("/api/executor/capabilities")

    assert res.status_code == 200
    data = res.json()
    assert data["recording_available"] is True
    assert "chrome" in data["headed_browsers"]


def test_get_capabilities_headless_only(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "browsers": [{"id": "chromium-headless", "headless": True}]
        }
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = inst

        res = client.get("/api/executor/capabilities")

    assert res.status_code == 200
    assert res.json()["recording_available"] is False


# ---------------------------------------------------------------------------
# GET /api/executor/config
# ---------------------------------------------------------------------------

def test_get_executor_config_success(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"preload": True, "running": False}
        inst.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = inst

        res = client.get("/api/executor/config")

    assert res.status_code == 200
    assert res.json()["preload"] is True


def test_get_executor_config_request_error(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.get = AsyncMock(side_effect=httpx.RequestError("down"))
        mock_cls.return_value = inst

        res = client.get("/api/executor/config")

    assert res.status_code == 503


def test_get_executor_config_http_error(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        inst.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        ))
        mock_cls.return_value = inst

        res = client.get("/api/executor/config")

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/executor/config
# ---------------------------------------------------------------------------

def test_update_executor_config_success(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"preload": False}
        inst.post = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = inst

        res = client.post("/api/executor/config", json={"preload": False})

    assert res.status_code == 200


def test_update_executor_config_request_error(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        inst.post = AsyncMock(side_effect=httpx.RequestError("down"))
        mock_cls.return_value = inst

        res = client.post("/api/executor/config", json={"preload": True})

    assert res.status_code == 503


def test_update_executor_config_http_error(client):
    with patch("api.routes.executor.httpx.AsyncClient") as mock_cls:
        inst = MagicMock()
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Unprocessable"
        inst.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "422", request=MagicMock(), response=mock_resp
        ))
        mock_cls.return_value = inst

        res = client.post("/api/executor/config", json={"preload": True})

    assert res.status_code == 422
