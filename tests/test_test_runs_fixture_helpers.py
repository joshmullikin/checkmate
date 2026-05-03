import json
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

from api.routes import test_runs as test_runs_routes
from db import crud
import db.encryption as encryption
from db.models import FixtureCreate, ProjectCreate


def _project(db_session):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name="Fixture Helper Project",
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def test_fixture_helper_no_ids_returns_empty(db_session):
    project = _project(db_session)
    steps, display, cached = test_runs_routes._get_fixture_steps_by_ids(
        db_session, [], project.id, "chromium-headless"
    )
    assert steps == []
    assert display == []
    assert cached is False


def test_fixture_helper_cache_miss_returns_setup_plus_capture(db_session):
    project = _project(db_session)
    fixture = crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=project.id,
            name="Login Fixture",
            description="",
            setup_steps=json.dumps([{"action": "navigate", "value": "/login"}]),
            scope="cached",
            cache_ttl_seconds=300,
        ),
    )

    steps, display, cached = test_runs_routes._get_fixture_steps_by_ids(
        db_session, [fixture.id], project.id, "chromium-headless"
    )

    assert cached is False
    assert len(steps) == 2
    assert steps[0]["action"] == "navigate"
    assert steps[1]["action"] == "capture_state"
    assert len(display) == 2


def test_fixture_helper_cache_hit_returns_restore_state(db_session):
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _project(db_session)
    fixture = crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=project.id,
            name="Cached Login",
            description="",
            setup_steps=json.dumps([{"action": "navigate", "value": "/login"}]),
            scope="cached",
            cache_ttl_seconds=300,
        ),
    )

    crud.create_fixture_state(
        db_session,
        fixture_id=fixture.id,
        project_id=project.id,
        url="https://example.com/dashboard",
        state_json=json.dumps({"cookies": []}),
        browser="chromium-headless",
        expires_at=datetime.utcnow() + timedelta(seconds=600),
    )

    steps, display, cached = test_runs_routes._get_fixture_steps_by_ids(
        db_session, [fixture.id], project.id, "chromium-headless"
    )

    assert cached is True
    assert len(steps) == 1
    assert steps[0]["action"] == "restore_state"
    assert "state" in steps[0]["value"]
    assert display[0]["value"] == "[cached browser state]"
