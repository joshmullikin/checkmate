from unittest.mock import AsyncMock, patch

from db import crud
from db.models import ProjectCreate, RunStatus, RunTrigger, TestRunCreate


def _create_project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="Runs Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def test_create_and_get_test_run_route(client, db_session):
    project = _create_project(db_session)
    payload = {
        "project_id": project.id,
        "test_case_id": None,
        "trigger": "manual",
        "status": "pending",
        "thread_id": "thread-123",
        "batch_label": "batch-a",
        "browser": "chromium",
    }

    create_res = client.post("/api/test-runs", json=payload)
    assert create_res.status_code == 200
    run_id = create_res.json()["id"]

    get_res = client.get(f"/api/test-runs/{run_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == run_id


def test_list_project_runs_with_and_without_thread_filter(client, db_session):
    project = _create_project(db_session)
    crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=None,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PENDING,
            thread_id="batch-1",
            batch_label="B1",
            browser="chromium",
        ),
    )
    crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=None,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PENDING,
            thread_id="batch-2",
            batch_label="B2",
            browser="chromium",
        ),
    )

    all_runs = client.get(f"/api/test-runs/project/{project.id}")
    assert all_runs.status_code == 200
    assert len(all_runs.json()) == 2

    batch_runs = client.get(f"/api/test-runs/project/{project.id}?thread_id=batch-1")
    assert batch_runs.status_code == 200
    assert len(batch_runs.json()) == 1
    assert batch_runs.json()[0]["thread_id"] == "batch-1"


def test_browsers_endpoint_returns_data_when_executor_available(client):
    with patch("api.routes.test_runs.PlaywrightExecutorClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.get_browsers = AsyncMock(
            return_value={
                "browsers": [
                    {"id": "chromium", "name": "Chromium", "headless": True},
                    {"id": "chrome", "name": "Google Chrome", "headless": False},
                ],
                "default": "chromium",
            }
        )
        mock_client.close = AsyncMock()

        res = client.get("/api/test-runs/browsers")
        assert res.status_code == 200

        data = res.json()
        assert data["default"] == "chromium"
        assert len(data["browsers"]) == 2


def test_browsers_endpoint_returns_empty_when_executor_fails(client):
    with patch("api.routes.test_runs.PlaywrightExecutorClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.get_browsers = AsyncMock(side_effect=RuntimeError("executor down"))
        mock_client.close = AsyncMock()

        res = client.get("/api/test-runs/browsers")
        assert res.status_code == 200
        assert res.json() == {"browsers": [], "default": None}