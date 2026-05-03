import json
from unittest.mock import MagicMock

import pytest

from db import crud
from db.models import TestCaseStatus, TestFolderCreate, TestFolderUpdate
from tests.crud_harness import create_project, create_test_case


def test_create_folder_parent_not_found(db_session):
    proj = create_project(db_session, "FolderParentNotFound")
    with pytest.raises(ValueError, match="Parent folder not found"):
        crud.create_folder(
            db_session,
            TestFolderCreate(project_id=proj.id, name="Child", parent_id=999999),
        )


def test_update_folder_with_root_parent(db_session):
    proj = create_project(db_session, "FolderReparent")
    root1 = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj.id, name="Root1")
    )
    root2 = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj.id, name="Root2")
    )
    result = crud.update_folder(db_session, root1.id, TestFolderUpdate(parent_id=root2.id))
    assert result.parent_id == root2.id


def test_update_folder_extra_key_via_mock(db_session):
    proj = create_project(db_session, "FolderMock")
    folder = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj.id, name="Fold")
    )
    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "renamed", "__bogus__": "x"}
    result = crud.update_folder(db_session, folder.id, fake)
    assert result.name == "renamed"


def test_delete_smart_folder(db_session):
    proj = create_project(db_session, "SmartDelete")
    folder = crud.create_folder(
        db_session,
        TestFolderCreate(
            project_id=proj.id,
            name="SmartFolder",
            folder_type="smart",
            smart_criteria=json.dumps({"tags": ["smoke"]}),
        ),
    )
    assert crud.delete_folder(db_session, folder.id) is True
    assert crud.get_folder(db_session, folder.id) is None


def test_compute_smart_folder_no_tags_filter(db_session):
    proj = create_project(db_session, "SmartNoTags")
    folder = crud.create_folder(
        db_session,
        TestFolderCreate(
            project_id=proj.id,
            name="Smart",
            folder_type="smart",
            smart_criteria=json.dumps({"statuses": ["approved"], "tags": []}),
        ),
    )
    create_test_case(db_session, proj.id, name="ApprovedTC", status=TestCaseStatus.APPROVED)
    matches = crud.compute_smart_folder_tests(db_session, folder)
    assert len(matches) >= 1


def test_move_test_case_to_root(db_session):
    proj = create_project(db_session, "MoveToRoot")
    folder = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj.id, name="Folder")
    )
    tc = create_test_case(db_session, proj.id)
    crud.move_test_case_to_folder(db_session, tc.id, folder.id)
    result = crud.move_test_case_to_folder(db_session, tc.id, None)
    assert result.folder_id is None


def test_move_folder_to_root(db_session):
    proj = create_project(db_session, "MoveFolderRoot")
    root = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj.id, name="Root")
    )
    child = crud.create_folder(
        db_session,
        TestFolderCreate(project_id=proj.id, name="Child", parent_id=root.id),
    )
    result = crud.move_folder(db_session, child.id, None)
    assert result.parent_id is None


def test_update_smart_folder_filters_disallowed_fields(db_session):
    proj = create_project(db_session, "SmartFolderFilter")
    smart = crud.create_folder(
        db_session,
        TestFolderCreate(
            project_id=proj.id,
            name="Smart",
            folder_type="smart",
            smart_criteria=json.dumps({"tags": ["smoke"]}),
        ),
    )
    root = crud.create_folder(db_session, TestFolderCreate(project_id=proj.id, name="Root"))

    # parent_id is not in allowed fields for smart folders and should be ignored.
    updated = crud.update_folder(
        db_session,
        smart.id,
        TestFolderUpdate(parent_id=root.id, name="Smart Renamed", description="d"),
    )
    assert updated.name == "Smart Renamed"
    assert updated.parent_id is None


def test_update_folder_parent_validation_errors(db_session):
    proj1 = create_project(db_session, "UpdateParentP1")
    proj2 = create_project(db_session, "UpdateParentP2")

    target = crud.create_folder(db_session, TestFolderCreate(project_id=proj1.id, name="Target"))
    root = crud.create_folder(db_session, TestFolderCreate(project_id=proj1.id, name="Root"))
    child = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj1.id, name="Child", parent_id=root.id)
    )
    cross = crud.create_folder(db_session, TestFolderCreate(project_id=proj2.id, name="Cross"))

    with pytest.raises(ValueError, match="own parent"):
        crud.update_folder(db_session, target.id, TestFolderUpdate(parent_id=target.id))

    with pytest.raises(ValueError, match="Parent folder not found"):
        crud.update_folder(db_session, target.id, TestFolderUpdate(parent_id=999999))

    with pytest.raises(ValueError, match="different project"):
        crud.update_folder(db_session, target.id, TestFolderUpdate(parent_id=cross.id))

    with pytest.raises(ValueError, match="Maximum folder nesting depth"):
        crud.update_folder(db_session, target.id, TestFolderUpdate(parent_id=child.id))


def test_move_test_case_to_folder_guard_errors(db_session):
    proj1 = create_project(db_session, "MoveTCProject1")
    proj2 = create_project(db_session, "MoveTCProject2")

    tc = create_test_case(db_session, proj1.id)
    cross_project_folder = crud.create_folder(
        db_session, TestFolderCreate(project_id=proj2.id, name="Cross")
    )
    smart_folder = crud.create_folder(
        db_session,
        TestFolderCreate(
            project_id=proj1.id,
            name="Smart",
            folder_type="smart",
            smart_criteria=json.dumps({"tags": ["smoke"]}),
        ),
    )

    with pytest.raises(ValueError, match="different project"):
        crud.move_test_case_to_folder(db_session, tc.id, cross_project_folder.id)

    with pytest.raises(ValueError, match="smart folder"):
        crud.move_test_case_to_folder(db_session, tc.id, smart_folder.id)


def test_move_folder_parent_guard_errors(db_session):
    proj1 = create_project(db_session, "MoveFolderP1")
    proj2 = create_project(db_session, "MoveFolderP2")

    target = crud.create_folder(db_session, TestFolderCreate(project_id=proj1.id, name="Target"))
    cross_parent = crud.create_folder(db_session, TestFolderCreate(project_id=proj2.id, name="Cross"))

    with pytest.raises(ValueError, match="Parent folder not found"):
        crud.move_folder(db_session, target.id, 999999)

    with pytest.raises(ValueError, match="different project"):
        crud.move_folder(db_session, target.id, cross_parent.id)
