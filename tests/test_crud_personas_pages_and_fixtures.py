import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from db import crud
from db.models import (
    FixtureUpdate,
    PageCreate,
    PageUpdate,
    PersonaCreate,
    PersonaUpdate,
)
from tests.crud_harness import create_fixture, create_project, reset_encryption


def test_update_persona_not_found(db_session):
    assert crud.update_persona(db_session, 999999, PersonaUpdate(name="x")) is None


def test_update_persona_extra_key_via_mock(db_session):
    reset_encryption()

    proj = create_project(db_session, "PersonaMock")
    persona = crud.create_persona(
        db_session,
        PersonaCreate(project_id=proj.id, name="user", username="user"),
    )
    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "newname", "__bogus__": "ignored"}
    result = crud.update_persona(db_session, persona.id, fake)
    assert result.name == "newname"


def test_delete_persona_not_found(db_session):
    assert crud.delete_persona(db_session, 999999) is False


def test_update_page_not_found(db_session):
    assert crud.update_page(db_session, 999999, PageUpdate(name="x")) is None


def test_update_page_extra_key_via_mock(db_session):
    proj = create_project(db_session, "PageMock")
    page = crud.create_page(
        db_session, PageCreate(project_id=proj.id, name="pg", path="/pg")
    )
    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "updated", "__bogus__": "x"}
    result = crud.update_page(db_session, page.id, fake)
    assert result.name == "updated"


def test_delete_page_not_found(db_session):
    assert crud.delete_page(db_session, 999999) is False


def test_update_fixture_not_found(db_session):
    assert crud.update_fixture(db_session, 999999, FixtureUpdate(name="x")) is None


def test_update_fixture_extra_key_via_mock(db_session):
    proj = create_project(db_session, "FixtureMock")
    fix = create_fixture(db_session, proj.id)
    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "new_fixture", "__bogus__": "x"}
    result = crud.update_fixture(db_session, fix.id, fake)
    assert result.name == "new_fixture"


def test_delete_fixture_not_found(db_session):
    assert crud.delete_fixture(db_session, 999999) is False


def test_get_fixture_state_not_found(db_session):
    assert crud.get_fixture_state(db_session, 999999) is None


def test_get_fixture_state_found(db_session):
    reset_encryption()

    proj = create_project(db_session, "FSGetProject")
    fix = create_fixture(db_session, proj.id)
    state = crud.create_fixture_state(
        db_session,
        fixture_id=fix.id,
        project_id=proj.id,
        url="https://example.com",
        state_json=json.dumps({"cookies": []}),
        browser="chromium",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    found = crud.get_fixture_state(db_session, state.id)
    assert found.id == state.id


def test_get_decrypted_fixture_state_no_encrypted(db_session):
    reset_encryption()

    proj = create_project(db_session, "DecryptNoEnc")
    fix = create_fixture(db_session, proj.id)
    state = crud.create_fixture_state(
        db_session,
        fixture_id=fix.id,
        project_id=proj.id,
        url=None,
        state_json=None,
        browser=None,
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    result = crud.get_decrypted_fixture_state(db_session, state)
    assert result["state"] is None
    assert result["url"] is None


def test_update_persona_encrypts_password(db_session):
    reset_encryption()

    proj = create_project(db_session, "PersonaPasswordEncrypt")
    persona = crud.create_persona(
        db_session,
        PersonaCreate(project_id=proj.id, name="login-user", username="login-user"),
    )
    assert persona.encrypted_password is None

    updated = crud.update_persona(db_session, persona.id, PersonaUpdate(password="new-secret"))
    assert updated is not None
    assert updated.encrypted_password is not None
