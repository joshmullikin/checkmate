import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from db import crud
from db.models import EnvironmentCreate, EnvironmentUpdate, ProjectCreate, RunStatus, RunTrigger, TestCaseCreate, TestCaseStatus, TestDataCreate, TestRunCreate


def _make_project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="CRUD Dashboard Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def test_crud_get_dashboard_stats_basic(db_session):
    project = _make_project(db_session)
    result = crud.get_project_dashboard(db_session, project.id)
    assert "kpis" in result
    assert "status_breakdown" in result
    assert "daily_runs" in result


def test_crud_get_dashboard_stats_with_runs(db_session):
    project = _make_project(db_session)
    test_case = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="Dashboard TC",
            description="",
            natural_query="dashboard test",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )
    run = crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=test_case.id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PASSED,
        ),
    )
    crud.update_test_run(
        db_session,
        run.id,
        {
            "started_at": datetime.utcnow() - timedelta(minutes=1),
            "completed_at": datetime.utcnow(),
            "pass_count": 1,
            "error_count": 0,
            "summary": "Passed",
            "browser": "chromium",
        },
    )

    result = crud.get_project_dashboard(db_session, project.id)
    assert result["status_breakdown"]["passed"] >= 1


def test_crud_create_environment_with_default(db_session):
    project = _make_project(db_session)
    env1 = crud.create_environment(
        db_session,
        EnvironmentCreate(project_id=project.id, name="Env1", base_url="https://env1.example.com", variables={}, is_default=True),
    )
    env2 = crud.create_environment(
        db_session,
        EnvironmentCreate(project_id=project.id, name="Env2", base_url="https://env2.example.com", variables={}, is_default=True),
    )
    db_session.refresh(env1)
    assert env1.is_default is False
    assert env2.is_default is True


def test_crud_update_environment_with_default(db_session):
    project = _make_project(db_session)
    env1 = crud.create_environment(
        db_session,
        EnvironmentCreate(project_id=project.id, name="E1", base_url="https://e1.example.com", variables={}, is_default=True),
    )
    env2 = crud.create_environment(
        db_session,
        EnvironmentCreate(project_id=project.id, name="E2", base_url="https://e2.example.com", variables={}, is_default=False),
    )
    crud.update_environment(db_session, env2.id, EnvironmentUpdate(is_default=True))
    db_session.refresh(env1)
    assert env1.is_default is False


def test_crud_update_environment_not_found_returns_none(db_session):
    assert crud.update_environment(db_session, 99999, EnvironmentUpdate(name="x")) is None


def test_crud_delete_environment_not_found_returns_false(db_session):
    assert crud.delete_environment(db_session, 99999) is False


def test_crud_get_test_cases_by_tags_empty(db_session):
    project = _make_project(db_session)
    assert crud.get_test_cases_by_tags(db_session, project.id, ["nonexistent_tag_xyz"]) == []


def test_crud_compute_smart_folder_tests_no_criteria(db_session):
    folder = SimpleNamespace(project_id=1, get_smart_criteria=lambda: {})
    assert crud.compute_smart_folder_tests(db_session, folder) == []


def test_crud_compute_smart_folder_tests_with_statuses_and_tags(db_session):
    project = _make_project(db_session)
    test_case = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="Smart TC",
            description="",
            natural_query="smart test",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )
    folder = SimpleNamespace(project_id=project.id, get_smart_criteria=lambda: {"tags": ["smoke"], "statuses": ["active"]})
    result = crud.compute_smart_folder_tests(db_session, folder)
    assert any(item.id == test_case.id for item in result)


def test_crud_delete_schedule_not_found(db_session):
    assert crud.delete_schedule(db_session, 99999) is False


def test_crud_update_scheduled_run_not_found(db_session):
    assert crud.update_scheduled_run(db_session, 99999, {"status": "passed"}) is None


def test_crud_get_scheduled_runs_by_schedule(db_session):
    assert crud.get_scheduled_runs_by_schedule(db_session, 99999) == []


def test_crud_get_scheduled_runs_by_project(db_session):
    assert crud.get_scheduled_runs_by_project(db_session, 99999) == []


def test_crud_move_test_case_to_folder_not_found(db_session):
    assert crud.move_test_case_to_folder(db_session, 99999, None) is None


def test_crud_move_test_case_to_folder_nonexistent_folder_raises(db_session):
    project = _make_project(db_session)
    test_case = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="TC move",
            description="",
            natural_query="move test",
            steps="[]",
            tags="[]",
            status=TestCaseStatus.ACTIVE,
        ),
    )
    with pytest.raises(ValueError, match="Target folder not found"):
        crud.move_test_case_to_folder(db_session, test_case.id, 99999)


def test_get_environment(db_session):
    project = _make_project(db_session)
    env = crud.create_environment(
        db_session,
        EnvironmentCreate(
            project_id=project.id,
            name="DEV",
            base_url="https://dev.example.com",
            variables={"API_URL": "https://dev.example.com/api"},
            is_default=False,
        ),
    )
    fetched = crud.get_environment(db_session, env.id)
    assert fetched is not None
    assert fetched.id == env.id


def test_get_default_environment(db_session):
    project = _make_project(db_session)
    crud.create_environment(
        db_session,
        EnvironmentCreate(
            project_id=project.id,
            name="DEV",
            base_url="https://dev.example.com",
            variables={},
            is_default=False,
        ),
    )
    default_env = crud.create_environment(
        db_session,
        EnvironmentCreate(
            project_id=project.id,
            name="STAGING",
            base_url="https://staging.example.com",
            variables={},
            is_default=True,
        ),
    )
    found = crud.get_default_environment(db_session, project.id)
    assert found is not None
    assert found.id == default_env.id


def test_update_environment_with_variables_dict(db_session):
    project = _make_project(db_session)
    env = crud.create_environment(
        db_session,
        EnvironmentCreate(
            project_id=project.id,
            name="DEV",
            base_url="https://dev.example.com",
            variables={"A": "1"},
            is_default=False,
        ),
    )
    updated = crud.update_environment(
        db_session,
        env.id,
        EnvironmentUpdate(variables={"A": "2", "B": "3"}),
    )
    assert updated.get_variables() == {"A": "2", "B": "3"}


def test_update_environment_extra_key_via_mock(db_session):
    project = _make_project(db_session)
    env = crud.create_environment(
        db_session,
        EnvironmentCreate(
            project_id=project.id,
            name="DEV",
            base_url="https://dev.example.com",
            variables={},
            is_default=False,
        ),
    )
    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "QA", "__bogus__": "x"}
    updated = crud.update_environment(db_session, env.id, fake)
    assert updated.name == "QA"


def test_dashboard_conditional_recommendation(db_session):
    project = _make_project(db_session)
    tc1 = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="TC1",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )
    tc2 = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="TC2",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )
    crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="TC3",
            description="",
            natural_query="not run",
            steps="[]",
            tags=json.dumps(["regression"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )

    for tc in (tc1, tc2):
        run = crud.create_test_run(
            db_session,
            TestRunCreate(
                project_id=project.id,
                test_case_id=tc.id,
                trigger=RunTrigger.MANUAL,
                status=RunStatus.PASSED,
            ),
        )
        crud.update_test_run(
            db_session,
            run.id,
            {
                "started_at": datetime.utcnow() - timedelta(seconds=10),
                "completed_at": datetime.utcnow(),
                "browser": "chromium",
            },
        )

    dashboard = crud.get_project_dashboard(db_session, project.id)
    assert dashboard["release_recommendation"] == "CONDITIONAL"


def test_dashboard_malformed_tags(db_session):
    project = _make_project(db_session)
    crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="BadTag TC",
            description="",
            natural_query="test",
            steps="[]",
            status=TestCaseStatus.ACTIVE,
            tags="not-valid-json",
        ),
    )
    dashboard = crud.get_project_dashboard(db_session, project.id)
    assert "module_health" in dashboard


def test_dashboard_tracks_failed_statuses_and_bottlenecks(db_session):
    project = _make_project(db_session)
    tc = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="Failing TC",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["auth"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )

    run = crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=tc.id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.FAILED,
            browser="chromium",
        ),
    )
    crud.update_test_run(
        db_session,
        run.id,
        {
            "started_at": datetime.utcnow() - timedelta(seconds=30),
            "completed_at": datetime.utcnow(),
        },
    )

    dashboard = crud.get_project_dashboard(db_session, project.id)
    assert dashboard["status_breakdown"]["failed"] >= 1
    assert any(day["failed"] >= 1 for day in dashboard["daily_runs"])
    assert any(item["module"] == "auth" and item["failed"] >= 1 for item in dashboard["module_health"])
    assert any(item["module"] == "auth" and item["failed"] >= 1 for item in dashboard["top_bottlenecks"])


def test_get_test_cases_by_tags_matches_runnable_only(db_session):
    project = _make_project(db_session)
    active = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="Active Smoke",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )
    approved = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="Approved Smoke",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.APPROVED,
        ),
    )
    crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="Draft Smoke",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.DRAFT,
        ),
    )

    matched = crud.get_test_cases_by_tags(db_session, project.id, ["smoke"])
    names = {tc.name for tc in matched}
    assert active.name in names
    assert approved.name in names
    assert "Draft Smoke" not in names


def test_get_test_data_by_project_environment_filter_includes_global(db_session):
    project = _make_project(db_session)
    env_a = crud.create_environment(
        db_session,
        EnvironmentCreate(
            project_id=project.id,
            name="A",
            base_url="https://a.example.com",
            variables={},
            is_default=False,
        ),
    )

    global_td = crud.create_test_data(
        db_session,
        TestDataCreate(
            project_id=project.id,
            name="global",
            data='[{"k": "v"}]',
            tags='["common"]',
            environment_id=None,
        ),
    )
    env_td = crud.create_test_data(
        db_session,
        TestDataCreate(
            project_id=project.id,
            name="env-a",
            data='[{"k": "a"}]',
            tags='["env"]',
            environment_id=env_a.id,
        ),
    )

    rows = crud.get_test_data_by_project(db_session, project.id, environment_id=env_a.id)
    ids = {row.id for row in rows}
    assert global_td.id in ids
    assert env_td.id in ids


def test_dashboard_recent_run_duration_can_be_none(db_session):
    project = _make_project(db_session)
    tc = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="No Duration TC",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )

    # Status is terminal so it appears in recent runs, but no started/completed
    # timestamps means duration_ms should remain None.
    crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=tc.id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PASSED,
            browser="chromium",
        ),
    )

    dashboard = crud.get_project_dashboard(db_session, project.id)
    assert any(item["test_case_name"] == "No Duration TC" and item["duration_ms"] is None for item in dashboard["recent_runs"])


def test_get_test_cases_by_tags_checks_multiple_requested_tags(db_session):
    project = _make_project(db_session)
    crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="MultiTagMatch",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["smoke"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )

    # First requested tag misses, second matches; this exercises the generator
    # loop inside any(tag in tc_tags for tag in tags).
    matched = crud.get_test_cases_by_tags(db_session, project.id, ["missing", "smoke"])
    names = {tc.name for tc in matched}
    assert "MultiTagMatch" in names


def test_get_test_cases_by_tags_non_match_skips_row(db_session):
    project = _make_project(db_session)
    crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project.id,
            name="NoMatch",
            description="",
            natural_query="run",
            steps="[]",
            tags=json.dumps(["regression"]),
            status=TestCaseStatus.ACTIVE,
        ),
    )

    # Ensures the if-any condition evaluates false for at least one runnable row.
    matched = crud.get_test_cases_by_tags(db_session, project.id, ["smoke"])
    assert all(tc.name != "NoMatch" for tc in matched)
