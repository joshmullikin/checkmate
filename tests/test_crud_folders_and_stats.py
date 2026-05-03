import json
from datetime import datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from db import crud
import db.encryption as encryption
from db.models import (
    FixtureCreate,
    ProjectCreate,
    RunStatus,
    RunTrigger,
    TestCaseCreate,
    TestCaseStatus,
    TestFolderCreate,
    TestFolderUpdate,
    TestRunCreate,
)


def _project(name="Folder Project"):
    return ProjectCreate(
        name=name,
        description="",
        base_url="https://example.com",
        config="{}",
        base_prompt="",
        page_load_state="load",
    )


def _test_case(project_id: int, name="Case", folder_id=None, tags=None, status="draft"):
    return TestCaseCreate(
        project_id=project_id,
        name=name,
        description="",
        natural_query="run",
        steps=json.dumps([{"action": "navigate", "value": "/"}]),
        expected_result="ok",
        tags=json.dumps(tags or []),
        fixture_ids=None,
        priority="medium",
        status=status,
        visibility="public",
        folder_id=folder_id,
        test_case_number=None,
    )


def test_create_folder_validates_parent_constraints(db_session):
    p1 = crud.create_project(db_session, _project("P1"))
    p2 = crud.create_project(db_session, _project("P2"))

    root = crud.create_folder(db_session, TestFolderCreate(project_id=p1.id, name="Root"))
    child = crud.create_folder(
        db_session, TestFolderCreate(project_id=p1.id, name="Child", parent_id=root.id)
    )

    with pytest.raises(ValueError, match="Maximum folder nesting depth is 2 levels"):
        crud.create_folder(
            db_session,
            TestFolderCreate(project_id=p1.id, name="Grandchild", parent_id=child.id),
        )

    with pytest.raises(ValueError, match="different project"):
        crud.create_folder(
            db_session,
            TestFolderCreate(project_id=p2.id, name="CrossProject", parent_id=root.id),
        )


def test_delete_folder_blocks_when_test_cases_exist(db_session):
    project = crud.create_project(db_session, _project())
    folder = crud.create_folder(db_session, TestFolderCreate(project_id=project.id, name="Folder"))
    crud.create_test_case(db_session, _test_case(project.id, folder_id=folder.id))

    with pytest.raises(ValueError, match="Move them to another folder"):
        crud.delete_folder(db_session, folder.id)


def test_delete_folder_orphans_children(db_session):
    project = crud.create_project(db_session, _project())
    parent = crud.create_folder(db_session, TestFolderCreate(project_id=project.id, name="Parent"))
    child = crud.create_folder(
        db_session, TestFolderCreate(project_id=project.id, name="Child", parent_id=parent.id)
    )

    assert crud.delete_folder(db_session, parent.id) is True
    moved_child = crud.get_folder(db_session, child.id)
    assert moved_child.parent_id is None


def test_compute_smart_folder_tests_filters_by_tags_and_status(db_session):
    project = crud.create_project(db_session, _project())
    smart = crud.create_folder(
        db_session,
        TestFolderCreate(
            project_id=project.id,
            name="Smart",
            folder_type="smart",
            smart_criteria=json.dumps({"tags": ["smoke"], "statuses": ["approved"]}),
        ),
    )

    crud.create_test_case(
        db_session,
        _test_case(project.id, name="A", tags=["smoke"], status=TestCaseStatus.APPROVED),
    )
    crud.create_test_case(
        db_session,
        _test_case(project.id, name="B", tags=["regression"], status=TestCaseStatus.APPROVED),
    )
    crud.create_test_case(
        db_session,
        _test_case(project.id, name="C", tags=["smoke"], status=TestCaseStatus.DRAFT),
    )

    matches = crud.compute_smart_folder_tests(db_session, smart)
    assert [m.name for m in matches] == ["A"]


def test_move_folder_prevents_circular_reference(db_session):
    project = crud.create_project(db_session, _project())
    parent = crud.create_folder(db_session, TestFolderCreate(project_id=project.id, name="Parent"))
    child = crud.create_folder(
        db_session, TestFolderCreate(project_id=project.id, name="Child", parent_id=parent.id)
    )

    with pytest.raises(ValueError, match="circular|Maximum folder nesting depth"):
        crud.move_folder(db_session, parent.id, child.id)


def test_fixture_state_expiry_cleanup(db_session):
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = crud.create_project(db_session, _project())
    fixture = crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=project.id,
            name="setup",
            description="",
            setup_steps=json.dumps([{"action": "navigate", "value": "/"}]),
            scope="cached",
            cache_ttl_seconds=60,
        ),
    )

    crud.create_fixture_state(
        db_session,
        fixture_id=fixture.id,
        project_id=project.id,
        url="https://example.com",
        state_json=json.dumps({"cookies": []}),
        browser="chromium",
        expires_at=datetime.utcnow() - timedelta(seconds=10),
    )

    deleted = crud.delete_expired_fixture_states(db_session)
    assert deleted == 1


def test_get_stats_and_dashboard_shapes(db_session):
    project = crud.create_project(db_session, _project())
    tc = crud.create_test_case(db_session, _test_case(project.id, name="Dashboard case", tags=["auth"]))

    run = crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project.id,
            test_case_id=tc.id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PASSED,
            thread_id=None,
            batch_label=None,
            browser="chromium",
        ),
    )
    crud.update_test_run(
        db_session,
        run.id,
        {
            "started_at": datetime.utcnow() - timedelta(seconds=3),
            "completed_at": datetime.utcnow(),
        },
    )

    stats = crud.get_stats(db_session)
    assert stats["total_projects"] >= 1
    assert "pass_rate" in stats