from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from api.main import app
from db.session import get_session_dep


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine)


@pytest.fixture
def db_session(test_engine):
    SQLModel.metadata.drop_all(test_engine)
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session


@pytest.fixture
def client(test_engine):
    def override_get_session_dep():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session_dep] = override_get_session_dep

    with patch("api.main.create_db_and_tables"), patch(
        "scheduler.scheduler_service.start", new=AsyncMock()
    ), patch("scheduler.scheduler_service.stop", new=AsyncMock()):
        with TestClient(app) as test_client:
            yield test_client

    app.dependency_overrides.clear()