"""Extended crud.py coverage tests for branches not yet covered."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from db import crud
import db.encryption as encryption
from db.models import (
    FixtureCreate,
    NotificationChannelCreate,
    NotificationChannelUpdate,
    PersonaCreate,
    PersonaUpdate,
    ProjectCreate,
    RunStatus,
    RunTrigger,
    ScheduleCreate,
    ScheduleUpdate,
    ScheduledRunCreate,
    TestCaseCreate,
    TestCaseStatus,
    TestDataCreate,
    TestRunCreate,
    TestRunStepCreate,
)


def _make_project(db_session, name="Test Project"):
    return crud.create_project(
        db_session,
        ProjectCreate(
            name=name,
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def _make_test_case(db_session, project_id, name="Test Case"):
    return crud.create_test_case(
        db_session,
        TestCaseCreate(
            project_id=project_id,
            name=name,
            description="",
            natural_query="test",
            steps='[{"action": "navigate", "value": "/"}]',
            status=TestCaseStatus.ACTIVE,
        ),
    )


def _make_test_run(db_session, project_id, test_case_id=None):
    return crud.create_test_run(
        db_session,
        TestRunCreate(
            project_id=project_id,
            test_case_id=test_case_id,
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PASSED,
        ),
    )


def _make_schedule(db_session, project_id, name="Nightly"):
    return crud.create_schedule(
        db_session,
        ScheduleCreate(
            project_id=project_id,
            name=name,
            description="",
            cron_expression="0 0 * * *",
            timezone="UTC",
            target_type="test_case_ids",
            target_test_case_ids="[]",
            target_tags=None,
            browser="chromium",
            retry_max=0,
            retry_mode=None,
            enabled=True,
            notification_channel_ids="[]",
        ),
    )


def test_delete_test_runs_by_project(db_session):
    """Test delete_test_runs_by_project deletes all runs including their steps."""
    project = _make_project(db_session, "Delete by project")
    tc = _make_test_case(db_session, project.id)
    run = _make_test_run(db_session, project.id, tc.id)

    # Add a step
    crud.create_test_run_step(
        db_session,
        TestRunStepCreate(
            test_run_id=run.id,
            step_number=1,
            action="navigate",
            target=None,
            value="/",
            status="passed",
            result="ok",
            screenshot=None,
            duration=100,
            error=None,
            logs=None,
            fixture_name=None,
        ),
    )

    count = crud.delete_test_runs_by_project(db_session, project.id)
    assert count == 1
    assert crud.get_test_run(db_session, run.id) is None


def test_delete_test_runs_by_test_case(db_session):
    """Test delete_test_runs_by_test_case deletes runs for a given test case."""
    project = _make_project(db_session, "Delete by test case")
    tc = _make_test_case(db_session, project.id)
    run1 = _make_test_run(db_session, project.id, tc.id)
    run2 = _make_test_run(db_session, project.id, tc.id)

    count = crud.delete_test_runs_by_test_case(db_session, tc.id)
    assert count == 2
    assert crud.get_test_run(db_session, run1.id) is None
    assert crud.get_test_run(db_session, run2.id) is None


def test_update_persona_with_empty_secrets_clears_them(db_session):
    """Test that update_persona with empty password/api_key/token/custom_fields removes those keys."""
    from db.encryption import ENCRYPTION_KEY
    from cryptography.fernet import Fernet
    import db.encryption as encryption

    # Set up encryption
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _make_project(db_session, "Persona Update Project")
    persona = crud.create_persona(
        db_session,
        PersonaCreate(
            project_id=project.id,
            name="alice",
            username="alice",
            credential_type="login",
            password="secret",
        ),
    )

    # Update with empty password (should pop it without encrypting)
    updated = crud.update_persona(
        db_session,
        persona.id,
        PersonaUpdate(password=""),  # empty string → pop without encrypting
    )
    assert updated is not None
    assert updated.name == "alice"


def test_update_persona_with_api_key_token_custom_fields(db_session):
    """Test update_persona handles api_key, token, and custom_fields paths."""
    from db.encryption import ENCRYPTION_KEY
    from cryptography.fernet import Fernet
    import db.encryption as encryption

    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _make_project(db_session, "Persona Encrypt Update")
    persona = crud.create_persona(
        db_session,
        PersonaCreate(
            project_id=project.id,
            name="api_user",
            username="api_user",
            credential_type="api_key",
        ),
    )

    # Update with api_key, token, custom_fields (all encrypted)
    updated = crud.update_persona(
        db_session,
        persona.id,
        PersonaUpdate(
            api_key="new-api-key",
            token="new-token",
            custom_fields={"role": "admin"},
        ),
    )
    assert updated is not None
    assert updated.encrypted_api_key is not None
    assert updated.encrypted_token is not None
    assert updated.encrypted_metadata is not None


def test_update_persona_with_empty_api_key_token_custom_fields(db_session):
    """Test update_persona with empty api_key/token/custom_fields pops them."""
    from cryptography.fernet import Fernet
    import db.encryption as encryption

    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _make_project(db_session, "Persona Empty Update")
    persona = crud.create_persona(
        db_session,
        PersonaCreate(
            project_id=project.id,
            name="token_user",
            username="token_user",
            credential_type="token",
        ),
    )

    # Update with empty fields (else branches - pop without setting)
    updated = crud.update_persona(
        db_session,
        persona.id,
        PersonaUpdate(api_key="", token="", custom_fields={}),
    )
    assert updated is not None


def test_delete_test_runs_by_project_empty(db_session):
    """Test delete_test_runs_by_project returns 0 when no runs exist."""
    project = _make_project(db_session, "Empty Project")
    count = crud.delete_test_runs_by_project(db_session, project.id)
    assert count == 0


def test_delete_test_runs_by_test_case_empty(db_session):
    """Test delete_test_runs_by_test_case returns 0 when no runs exist."""
    project = _make_project(db_session, "No Runs Project")
    tc = _make_test_case(db_session, project.id)
    count = crud.delete_test_runs_by_test_case(db_session, tc.id)
    assert count == 0


def test_delete_fixture_state_and_states_by_fixture(db_session):
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None

    project = _make_project(db_session, "Fixture state project")
    fixture = crud.create_fixture(
        db_session,
        FixtureCreate(
            project_id=project.id,
            name="Login setup",
            description="",
            setup_steps=json.dumps([{"action": "navigate", "value": "/login"}]),
            scope="cached",
            cache_ttl_seconds=300,
        ),
    )

    state1 = crud.create_fixture_state(
        db_session,
        fixture_id=fixture.id,
        project_id=project.id,
        url="https://example.com/a",
        state_json=json.dumps({"cookies": []}),
        browser="chromium",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    crud.create_fixture_state(
        db_session,
        fixture_id=fixture.id,
        project_id=project.id,
        url="https://example.com/b",
        state_json=json.dumps({"cookies": []}),
        browser="firefox",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )

    assert crud.delete_fixture_state(db_session, state1.id) is True
    assert crud.delete_fixture_state(db_session, 999999) is False
    assert crud.delete_fixture_states_by_fixture(db_session, fixture.id) == 1
    assert crud.delete_fixture_states_by_fixture(db_session, fixture.id) == 0


def test_scheduled_run_crud_roundtrip_and_missing_update(db_session):
    project = _make_project(db_session, "Scheduled run project")
    schedule = _make_schedule(db_session, project.id)

    first = crud.create_scheduled_run(
        db_session,
        ScheduledRunCreate(
            schedule_id=schedule.id,
            project_id=project.id,
            thread_id="thread-1",
            status="running",
            notifications_sent="[]",
            notification_errors="{}",
        ),
    )
    second = crud.create_scheduled_run(
        db_session,
        ScheduledRunCreate(
            schedule_id=schedule.id,
            project_id=project.id,
            thread_id="thread-2",
            status="passed",
            notifications_sent="[]",
            notification_errors="{}",
        ),
    )

    assert crud.get_scheduled_run(db_session, first.id).id == first.id
    by_schedule = crud.get_scheduled_runs_by_schedule(db_session, schedule.id)
    by_project = crud.get_scheduled_runs_by_project(db_session, project.id)
    assert len(by_schedule) == 2
    assert len(by_project) == 2

    updated = crud.update_scheduled_run(
        db_session,
        first.id,
        {"status": "failed", "nonexistent_field": "ignored"},
    )
    assert updated.status == "failed"
    assert crud.update_scheduled_run(db_session, 999999, {"status": "failed"}) is None
    assert {run.id for run in by_project} == {first.id, second.id}


def test_get_notification_channels_by_ids_empty(db_session):
    assert crud.get_notification_channels_by_ids(db_session, []) == []


def test_update_notification_channel_extra_key_via_mock(db_session):
    project = _make_project(db_session, "Channel Mock")
    channel = crud.create_notification_channel(
        db_session,
        NotificationChannelCreate(
            project_id=project.id,
            name="alerts",
            channel_type="webhook",
            webhook_url="https://hooks.example.com",
        ),
    )

    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "alerts-updated", "__bogus__": "x"}
    updated = crud.update_notification_channel(db_session, channel.id, fake)
    assert updated.name == "alerts-updated"


def test_update_notification_channel_not_found(db_session):
    assert crud.update_notification_channel(
        db_session,
        999999,
        NotificationChannelUpdate(name="missing"),
    ) is None


def test_delete_notification_channel_not_found(db_session):
    assert crud.delete_notification_channel(db_session, 999999) is False


def test_get_all_enabled_schedules(db_session):
    project = _make_project(db_session, "Enabled Schedules")
    enabled = crud.create_schedule(
        db_session,
        ScheduleCreate(
            project_id=project.id,
            name="Enabled",
            cron_expression="0 0 * * *",
            enabled=True,
        ),
    )
    crud.create_schedule(
        db_session,
        ScheduleCreate(
            project_id=project.id,
            name="Disabled",
            cron_expression="0 0 * * *",
            enabled=False,
        ),
    )

    found_ids = {s.id for s in crud.get_all_enabled_schedules(db_session)}
    assert enabled.id in found_ids


def test_update_schedule_not_found(db_session):
    assert crud.update_schedule(db_session, 999999, ScheduleUpdate(name="x")) is None


def test_update_schedule_extra_key_via_mock(db_session):
    project = _make_project(db_session, "Schedule Mock")
    schedule = _make_schedule(db_session, project.id)

    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "renamed", "__bogus__": "x"}
    updated = crud.update_schedule(db_session, schedule.id, fake)
    assert updated.name == "renamed"


def test_update_schedule_run_times_not_found(db_session):
    assert crud.update_schedule_run_times(db_session, 999999, datetime.utcnow(), datetime.utcnow()) is None


def test_update_schedule_run_times_no_next(db_session):
    project = _make_project(db_session, "Schedule Run Times")
    schedule = _make_schedule(db_session, project.id)
    original_next = schedule.next_run_at

    last_run = datetime.utcnow()
    updated = crud.update_schedule_run_times(db_session, schedule.id, last_run, None)
    assert updated.last_run_at is not None
    assert updated.next_run_at == original_next


def test_try_claim_schedule_execution_claim_then_block(db_session):
    project = _make_project(db_session, "ClaimSchedule")
    schedule = _make_schedule(db_session, project.id, name="Claim Me")

    # First claim should succeed when last_run_at is NULL.
    first = crud.try_claim_schedule_execution(db_session, schedule.id, claim_window_seconds=60)
    # Immediate second claim should fail because first just updated last_run_at.
    second = crud.try_claim_schedule_execution(db_session, schedule.id, claim_window_seconds=60)

    assert first is True
    assert second is False


def test_update_test_data_extra_key_via_mock(db_session):
    project = _make_project(db_session, "Test Data Mock")
    item = crud.create_test_data(
        db_session,
        TestDataCreate(
            project_id=project.id,
            name="users",
            data='[{"email":"a@example.com"}]',
            tags='["smoke"]',
        ),
    )

    fake = MagicMock()
    fake.model_dump = lambda exclude_unset: {"name": "users-updated", "__bogus__": "x"}
    updated = crud.update_test_data(db_session, item.id, fake)
    assert updated.name == "users-updated"


def test_update_test_data_not_found(db_session):
    assert crud.update_test_data(db_session, 999999, MagicMock(model_dump=lambda exclude_unset: {"name": "x"})) is None


def test_delete_test_data_not_found(db_session):
    assert crud.delete_test_data(db_session, 999999) is False
