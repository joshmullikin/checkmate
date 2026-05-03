import json

from cryptography.fernet import Fernet

import db.encryption as encryption
from db import crud
from db.models import (
    FixtureCreate,
    ProjectCreate,
    RunStatus,
    RunTrigger,
    ScheduleCreate,
    TestCaseCreate,
    TestCaseStatus,
    TestRunCreate,
    TestRunStepCreate,
)


def reset_encryption() -> None:
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption._fernet = None


def create_project(session, name: str = "Wave2Project"):
    return crud.create_project(
        session,
        ProjectCreate(
            name=name,
            description="",
            base_url="https://example.com",
            config="{}",
            base_prompt="",
            page_load_state="load",
        ),
    )


def create_test_case(
    session,
    project_id: int,
    name: str = "TC",
    tags=None,
    status: TestCaseStatus = TestCaseStatus.ACTIVE,
):
    return crud.create_test_case(
        session,
        TestCaseCreate(
            project_id=project_id,
            name=name,
            description="",
            natural_query="test",
            steps='[{"action": "navigate", "value": "/"}]',
            status=status,
            tags=tags,
        ),
    )


def create_fixture(session, project_id: int, name: str = "Fixture"):
    return crud.create_fixture(
        session,
        FixtureCreate(
            project_id=project_id,
            name=name,
            description="",
            setup_steps='[{"action": "navigate", "value": "/login"}]',
            scope="cached",
            cache_ttl_seconds=300,
        ),
    )


def create_schedule(session, project_id: int, name: str = "Sched"):
    return crud.create_schedule(
        session,
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


def create_run(session, project_id: int, tc_id=None, status: RunStatus = RunStatus.PASSED):
    return crud.create_test_run(
        session,
        TestRunCreate(
            project_id=project_id,
            test_case_id=tc_id,
            trigger=RunTrigger.MANUAL,
            status=status,
        ),
    )


def create_test_run_step(session, run_id: int, duration: int = 50):
    return crud.create_test_run_step(
        session,
        TestRunStepCreate(
            test_run_id=run_id,
            step_number=1,
            action="navigate",
            target=None,
            value="/",
            status="passed",
            result="ok",
            screenshot=None,
            duration=duration,
            error=None,
            logs=None,
            fixture_name=None,
        ),
    )
