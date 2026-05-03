import json
from unittest.mock import AsyncMock

import pytest

from db import crud
from db.models import (
    ProjectCreate,
    RunStatus,
    StepStatus,
    TestCaseCreate,
    TestRunCreate,
    TestRunStepCreate,
)


def _project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="Healer Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def _test_case(db_session, project_id: int):
    return crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project_id,
            name="Login test",
            description="",
            natural_query="login flow",
            steps=json.dumps([
                {"action": "navigate", "value": "/login"},
                {"action": "click", "target": "Submit", "value": None},
            ]),
            expected_result="",
            tags=json.dumps([]),
            fixture_ids=None,
            priority="medium",
            status="draft",
            visibility="public",
            folder_id=None,
            test_case_number=None,
        ),
    )


def _run(db_session, project_id: int, test_case_id: int, status: RunStatus):
    return crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project_id,
            test_case_id=test_case_id,
            trigger="manual",
            status=status,
            thread_id=None,
            batch_label=None,
            browser=None,
        ),
    )


def _failed_step(db_session, run_id: int, test_case_id: int):
    return crud.create_test_run_step(
        db_session,
        TestRunStepCreate(
            test_run_id=run_id,
            test_case_id=test_case_id,
            step_number=2,
            action="click",
            target="Submit",
            value=None,
            status=StepStatus.FAILED,
            result=None,
            screenshot="base64",
            duration=100,
            error="Element not found",
            logs=None,
            fixture_name=None,
        ),
    )


def test_heal_route_validation_errors(client, db_session):
    project = _project(db_session)
    test_case = _test_case(db_session, project.id)

    missing_run = client.post(f"/api/test-cases/{test_case.id}/heal", json={"run_id": 99999})
    assert missing_run.status_code == 404

    other_case = _test_case(db_session, project.id)
    run_wrong_case = _run(db_session, project.id, other_case.id, RunStatus.FAILED)
    wrong_case = client.post(f"/api/test-cases/{test_case.id}/heal", json={"run_id": run_wrong_case.id})
    assert wrong_case.status_code == 400

    run_not_failed = _run(db_session, project.id, test_case.id, RunStatus.PASSED)
    not_failed = client.post(f"/api/test-cases/{test_case.id}/heal", json={"run_id": run_not_failed.id})
    assert not_failed.status_code == 400

    run_without_failed_steps = _run(db_session, project.id, test_case.id, RunStatus.FAILED)
    no_steps = client.post(f"/api/test-cases/{test_case.id}/heal", json={"run_id": run_without_failed_steps.id})
    assert no_steps.status_code == 400


def test_heal_route_success_with_mocked_scan_and_suggestion(client, db_session, monkeypatch):
    project = _project(db_session)
    test_case = _test_case(db_session, project.id)
    run = _run(db_session, project.id, test_case.id, RunStatus.FAILED)
    _failed_step(db_session, run.id, test_case.id)

    monkeypatch.setattr("api.routes.healer._scan_page_elements", AsyncMock(return_value=["Submit", "Cancel"]))
    monkeypatch.setattr(
        "api.routes.healer.suggest_heal",
        AsyncMock(
            return_value={
                "healed_steps": [
                    {
                        "action": "navigate",
                        "target": None,
                        "value": "/login",
                        "description": "Go to login",
                        "change_reason": None,
                    },
                    {
                        "action": "click",
                        "target": "Sign in",
                        "value": None,
                        "description": "Click corrected button",
                        "change_reason": "Matched closest visible element",
                    },
                ],
                "changed_step_numbers": [2],
                "explanation": "Updated stale button target based on page elements.",
                "confidence": 0.91,
            }
        ),
    )

    res = client.post(f"/api/test-cases/{test_case.id}/heal", json={"run_id": run.id})
    assert res.status_code == 200
    body = res.json()
    assert body["confidence"] == 0.91
    assert body["changed_step_numbers"] == [2]
    assert "explanation" in body


# ──────────────────────────────────────────────────────────────────────────────
# Test _scan_page_elements directly
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_page_elements_success(monkeypatch):
    """_scan_page_elements returns list of elements on success."""
    import httpx
    from api.routes.healer import _scan_page_elements
    from types import SimpleNamespace

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"elements": ["Login button", "Username input", "Password input"]}

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs): return _FakeResp()

    monkeypatch.setattr("api.routes.healer.httpx.AsyncClient", lambda timeout=20.0: _FakeClient())

    result = await _scan_page_elements("https://example.com/login")
    assert result == ["Login button", "Username input", "Password input"]


@pytest.mark.asyncio
async def test_scan_page_elements_http_error(monkeypatch):
    """_scan_page_elements returns None on httpx error."""
    import httpx
    from api.routes.healer import _scan_page_elements

    class _BrokenClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("Executor down")

    monkeypatch.setattr("api.routes.healer.httpx.AsyncClient", lambda timeout=20.0: _BrokenClient())

    result = await _scan_page_elements("https://example.com/login")
    assert result is None


@pytest.mark.asyncio
async def test_scan_page_elements_non_200(monkeypatch):
    """_scan_page_elements returns None on non-200 response."""
    from api.routes.healer import _scan_page_elements

    class _FakeResp:
        status_code = 503
        def json(self): return {}

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs): return _FakeResp()

    monkeypatch.setattr("api.routes.healer.httpx.AsyncClient", lambda timeout=20.0: _FakeClient())

    result = await _scan_page_elements("https://example.com/login")
    assert result is None


@pytest.mark.asyncio
async def test_scan_page_elements_empty_list(monkeypatch):
    """_scan_page_elements returns None when elements list is empty."""
    from api.routes.healer import _scan_page_elements

    class _FakeResp:
        status_code = 200
        def json(self): return {"elements": []}

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs): return _FakeResp()

    monkeypatch.setattr("api.routes.healer.httpx.AsyncClient", lambda timeout=20.0: _FakeClient())

    result = await _scan_page_elements("https://example.com/login")
    assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# Test _resolve_failing_page_url directly
# ──────────────────────────────────────────────────────────────────────────────

def test_resolve_failing_page_url_with_navigate_before_fail():
    """_resolve_failing_page_url returns last navigate URL before failing step."""
    from api.routes.healer import _resolve_failing_page_url

    steps = [
        {"step_number": 1, "action": "navigate", "value": "/login"},
        {"step_number": 2, "action": "click", "target": "Submit"},
    ]
    result = _resolve_failing_page_url("https://example.com", steps, failed_step_number=2)
    assert result == "https://example.com/login"


def test_resolve_failing_page_url_no_navigate_uses_base():
    """_resolve_failing_page_url falls back to base_url when no navigate found."""
    from api.routes.healer import _resolve_failing_page_url

    steps = [
        {"step_number": 1, "action": "click", "target": "Button"},
    ]
    result = _resolve_failing_page_url("https://example.com", steps, failed_step_number=1)
    assert "example.com" in result


def test_resolve_failing_page_url_absolute_url():
    """_resolve_failing_page_url returns absolute URL if navigate value is absolute."""
    from api.routes.healer import _resolve_failing_page_url

    steps = [
        {"step_number": 1, "action": "navigate", "value": "https://other.example.com/page"},
        {"step_number": 2, "action": "click", "target": "Submit"},
    ]
    result = _resolve_failing_page_url("https://example.com", steps, failed_step_number=2)
    assert result == "https://other.example.com/page"


def test_heal_test_case_not_found(client):
    """heal endpoint returns 404 for non-existent test case."""
    res = client.post("/api/test-cases/999999/heal", json={"run_id": 1})
    assert res.status_code == 404

