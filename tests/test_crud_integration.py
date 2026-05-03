import json

from db import crud
from db.models import (
    ProjectCreate,
    RunStatus,
    RunTrigger,
    TestCaseCreate,
    TestCaseStatus,
    TestRunCreate,
    TestRunStepCreate,
)


def _project_payload(name: str = "Checkout App") -> ProjectCreate:
    return ProjectCreate(
        name=name,
        description="Test project",
        base_url="https://example.com",
        config="{}",
        base_prompt="",
        page_load_state="load",
    )


def _test_case_payload(project_id: int, name: str = "Login flow") -> TestCaseCreate:
    return TestCaseCreate(
        project_id=project_id,
        name=name,
        description="",
        natural_query="Validate login",
        steps=json.dumps([
            {"action": "navigate", "value": "/login"},
            {"action": "type", "target": "#email", "value": "user@example.com"},
        ]),
        expected_result="User can sign in",
        tags=json.dumps(["smoke"]),
        fixture_ids=None,
        priority="medium",
        status="draft",
        visibility="public",
        folder_id=None,
        test_case_number=None,
    )


def test_create_project_sets_generated_prefix(db_session):
    project = crud.create_project(db_session, _project_payload("Check Mate"))
    assert project.id is not None
    assert project.test_case_prefix == "CM"


def test_create_test_case_increments_project_counter(db_session):
    project = crud.create_project(db_session, _project_payload())
    first = crud.create_test_case(db_session, _test_case_payload(project.id, "Case A"))
    second = crud.create_test_case(db_session, _test_case_payload(project.id, "Case B"))

    refreshed_project = crud.get_project(db_session, project.id)
    assert first.test_case_number == 1
    assert second.test_case_number == 2
    assert refreshed_project.next_test_case_number == 3


def test_update_test_case_status_validates_transitions(db_session):
    project = crud.create_project(db_session, _project_payload())
    test_case = crud.create_test_case(db_session, _test_case_payload(project.id))

    updated = crud.update_test_case_status(db_session, test_case.id, TestCaseStatus.READY)
    assert updated.status == TestCaseStatus.READY

    with_raises = False
    try:
        crud.update_test_case_status(db_session, test_case.id, TestCaseStatus.APPROVED)
    except ValueError:
        with_raises = True
    assert with_raises


def test_delete_project_cascades_related_records(db_session):
    project = crud.create_project(db_session, _project_payload())
    test_case = crud.create_test_case(db_session, _test_case_payload(project.id))
    test_run = crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=test_case.id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.RUNNING,
            thread_id="thread-1",
            batch_label=None,
            browser="chromium",
        ),
    )
    crud.create_test_run_step(
        db_session,
        TestRunStepCreate(
            test_run_id=test_run.id,
            test_case_id=test_case.id,
            step_number=1,
            action="navigate",
            target=None,
            value="/login",
            status="passed",
            result="ok",
            screenshot=None,
            duration=120,
            error=None,
            logs=None,
            fixture_name=None,
        ),
    )

    deleted = crud.delete_project(db_session, project.id)
    assert deleted is True
    assert crud.get_project(db_session, project.id) is None
    assert crud.get_test_case(db_session, test_case.id) is None
    assert crud.get_test_run(db_session, test_run.id) is None