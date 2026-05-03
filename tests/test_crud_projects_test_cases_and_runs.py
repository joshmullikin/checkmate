from db import crud
from db.models import (
    FixtureCreate,
    PageCreate,
    PersonaCreate,
    ProjectCreate,
    RunStatus,
    TestCaseCreate,
    TestCaseStatus,
    TestDataCreate,
)

from tests.crud_harness import (
    create_project,
    create_run,
    create_schedule,
    create_test_case,
    create_test_run_step,
)


def test_create_project_with_prefix_already_set(db_session):
    proj = crud.create_project(
        db_session,
        ProjectCreate(
            name="PrefixProject",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
            test_case_prefix="CUSTOM",
        ),
    )
    assert proj.test_case_prefix == "CUSTOM"


def test_update_project_invalid_key_ignored(db_session):
    proj = create_project(db_session, "InvalidKeyProject")
    result = crud.update_project(
        db_session, proj.id, {"__bogus__": "val", "name": "Updated"}
    )
    assert result.name == "Updated"


def test_delete_project_with_schedule(db_session):
    proj = create_project(db_session, "SchedProject")
    create_schedule(db_session, proj.id)
    assert crud.delete_project(db_session, proj.id) is True
    assert crud.get_project(db_session, proj.id) is None


def test_create_test_case_missing_project(db_session):
    tc = crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=999999,
            name="NoProject TC",
            description="",
            natural_query="test",
            steps="[]",
            status=TestCaseStatus.DRAFT,
        ),
    )
    assert tc.id is not None
    assert tc.test_case_number is None


def test_update_test_case_invalid_key_ignored(db_session):
    proj = create_project(db_session, "TCUpdate")
    tc = create_test_case(db_session, proj.id)
    result = crud.update_test_case(
        db_session, tc.id, {"__bogus__": "x", "name": "Renamed"}
    )
    assert result.name == "Renamed"


def test_delete_test_runs_by_test_case_with_steps(db_session):
    proj = create_project(db_session, "DeleteByTCWithSteps")
    tc = create_test_case(db_session, proj.id)
    run = create_run(db_session, proj.id, tc.id)
    create_test_run_step(db_session, run.id)

    count = crud.delete_test_runs_by_test_case(db_session, tc.id)
    assert count == 1
    assert crud.get_test_run(db_session, run.id) is None


def test_delete_test_run_with_steps(db_session):
    proj = create_project(db_session, "DeleteRunSteps")
    tc = create_test_case(db_session, proj.id)
    run = create_run(db_session, proj.id, tc.id)
    create_test_run_step(db_session, run.id, duration=100)

    assert crud.delete_test_run(db_session, run.id) is True
    assert crud.get_test_run(db_session, run.id) is None


def test_update_test_run_invalid_key_ignored(db_session):
    proj = create_project(db_session, "UpdateRunProject")
    run = create_run(db_session, proj.id)
    result = crud.update_test_run(
        db_session, run.id, {"__bogus__": "x", "status": RunStatus.FAILED}
    )
    assert result.status == RunStatus.FAILED


def test_delete_project_cascades_personas_pages_fixtures_and_test_data(db_session):
    proj = create_project(db_session, "CascadeProject")
    crud.create_persona(
        db_session,
        PersonaCreate(project_id=proj.id, name="admin", username="admin"),
    )
    crud.create_page(
        db_session,
        PageCreate(project_id=proj.id, name="home", path="/"),
    )
    crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=proj.id,
            name="setup",
            description="",
            setup_steps='[{"action": "navigate", "value": "/"}]',
            scope="cached",
            cache_ttl_seconds=60,
        ),
    )
    crud.create_test_data(
        db_session,
        TestDataCreate(project_id=proj.id, name="seed", data='[{"id": 1}]', tags='["smoke"]'),
    )

    assert crud.delete_project(db_session, proj.id) is True
    assert crud.get_project(db_session, proj.id) is None
    assert crud.get_personas_by_project(db_session, proj.id) == []
    assert crud.get_pages_by_project(db_session, proj.id) == []
    assert crud.get_fixtures_by_project(db_session, proj.id) == []
    assert crud.get_test_data_by_project(db_session, proj.id) == []


def test_delete_test_run_not_found(db_session):
    assert crud.delete_test_run(db_session, 999999) is False
