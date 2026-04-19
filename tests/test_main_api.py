from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import api.main as main_module


def test_root_and_health_endpoints():
    client = TestClient(main_module.app)

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["name"] == "QA Testing Agent"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}


def test_request_middleware_adds_request_id_header():
    client = TestClient(main_module.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"]


def test_lifespan_starts_and_stops_scheduler_once():
    with patch("api.main.create_db_and_tables") as mock_create_tables, patch(
        "scheduler.scheduler_service.start", new=AsyncMock()
    ) as mock_start, patch("scheduler.scheduler_service.stop", new=AsyncMock()) as mock_stop:
        with TestClient(main_module.app):
            pass

    mock_create_tables.assert_called_once()
    mock_start.assert_awaited_once()
    mock_stop.assert_awaited_once()
